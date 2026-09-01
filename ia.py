"""
Cliente de Ollama: conversación, streaming y embeddings.

Es el único módulo que habla con el modelo. Todo lo demás le pide texto o
vectores y no sabe qué motor hay detrás -- el día que el servidor cambie de
Ollama a otra cosa, se reescribe este archivo y nada más.

Dos decisiones que vienen del hardware, no del gusto:

· Se genera EN STREAMING. En CPU un modelo pequeño produce del orden de
  10 tokens por segundo; una respuesta de 300 tokens tarda medio minuto. Sin
  streaming el usuario mira una pantalla en blanco y concluye que se colgó.

· Hay UN turno de generación a la vez, con cerrojo. Ollama en CPU atendiendo
  dos conversaciones no las hace más rápidas: las hace lentas a las dos y se
  come la memoria. Es mejor decir "hay una consulta en curso" que dar dos
  respuestas malas.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Iterator

import httpx

URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MODELO_CHAT = os.getenv("MODELO_CHAT", "qwen2.5:3b-instruct")
MODELO_EMBED = os.getenv("MODELO_EMBED", "bge-m3")
TIMEOUT = int(os.getenv("IA_TIMEOUT", "600"))
CONTEXTO = int(os.getenv("IA_CONTEXTO", "8192"))

# El cerrojo del turno. `_en_uso` es informativo para poder decirle al
# usuario quién está ocupando el modelo, no para decidir nada.
_turno = threading.Lock()
_en_uso: dict = {"usuario": None, "desde": None}


class ModeloOcupado(Exception):
    """Alguien más está generando. No es un error del sistema: es una cola."""


def config() -> dict:
    return {"url": URL, "modelo_chat": MODELO_CHAT,
            "modelo_embed": MODELO_EMBED, "contexto": CONTEXTO,
            "ocupado": _turno.locked(),
            "ocupado_por": _en_uso["usuario"] if _turno.locked() else None}


def disponible() -> dict:
    """¿Está Ollama arriba y con los modelos que hacen falta?

    Se comprueba de verdad contra el servidor en vez de suponerlo: la causa
    número uno de que esto no funcione es que `ollama serve` no está
    corriendo, o que el modelo nunca se descargó.
    """
    try:
        r = httpx.get(f"{URL}/api/tags", timeout=5)
        r.raise_for_status()
        modelos = [m["name"] for m in r.json().get("models", [])]
    except Exception as e:
        return {"arriba": False, "error": str(e), "modelos": [],
                "falta_chat": True, "falta_embed": True}

    def tiene(nombre: str) -> bool:
        # Ollama reporta 'qwen2.5:3b-instruct'; el usuario puede haber
        # configurado 'qwen2.5:3b-instruct' o el nombre con :latest.
        base = nombre.split(":")[0]
        return any(m == nombre or m.split(":")[0] == base for m in modelos)

    return {"arriba": True, "error": None, "modelos": modelos,
            "falta_chat": not tiene(MODELO_CHAT),
            "falta_embed": not tiene(MODELO_EMBED)}


def modelos() -> list[str]:
    return disponible()["modelos"]


# =====================================================================
# EMBEDDINGS
# =====================================================================

def embeddings(textos: list[str], modelo: str | None = None) -> list[list[float]]:
    """Vectoriza una lista de textos.

    Va por lotes contra `/api/embed`, que acepta varios de una. Si el
    servidor es viejo y no lo tiene, cae a `/api/embeddings`, que va de a
    uno. La caída se hace por respuesta del servidor, no por versión
    supuesta.
    """
    if not textos:
        return []
    modelo = modelo or MODELO_EMBED
    with httpx.Client(timeout=TIMEOUT) as cli:
        try:
            r = cli.post(f"{URL}/api/embed",
                         json={"model": modelo, "input": textos})
            if r.status_code == 404:
                raise NotImplementedError
            r.raise_for_status()
            return r.json()["embeddings"]
        except NotImplementedError:
            salida = []
            for t in textos:
                r = cli.post(f"{URL}/api/embeddings",
                             json={"model": modelo, "prompt": t})
                r.raise_for_status()
                salida.append(r.json()["embedding"])
            return salida


def embedding(texto: str, modelo: str | None = None) -> list[float]:
    return embeddings([texto], modelo)[0]


# =====================================================================
# CONVERSACIÓN
# =====================================================================

def conversar(mensajes: list[dict], modelo: str | None = None,
              temperatura: float = 0.3,
              usuario: str | None = None) -> Iterator[dict]:
    """Genera la respuesta, trozo a trozo.

    Devuelve diccionarios en vez de texto suelto para poder distinguir un
    pedazo de respuesta del cierre con sus métricas -- quien consume esto
    necesita saber cuándo terminó y cuánto costó, no solo qué dijo.

    Lanza ModeloOcupado si hay otro turno en curso. No espera en cola: en
    CPU la espera puede ser de minutos, y es mejor devolver el control al
    usuario que dejarle una petición colgada.
    """
    if not _turno.acquire(blocking=False):
        raise ModeloOcupado(_en_uso["usuario"] or "otro usuario")

    _en_uso.update(usuario=usuario, desde=time.time())
    arranque = time.time()
    piezas = 0
    try:
        with httpx.Client(timeout=TIMEOUT) as cli:
            with cli.stream("POST", f"{URL}/api/chat", json={
                "model": modelo or MODELO_CHAT,
                "messages": mensajes,
                "stream": True,
                "options": {"temperature": float(temperatura),
                            "num_ctx": CONTEXTO},
            }) as r:
                r.raise_for_status()
                for linea in r.iter_lines():
                    if not linea:
                        continue
                    import json as _json
                    dato = _json.loads(linea)
                    trozo = (dato.get("message") or {}).get("content", "")
                    if trozo:
                        piezas += 1
                        yield {"tipo": "texto", "texto": trozo}
                    if dato.get("done"):
                        yield {"tipo": "fin",
                               "ms": int((time.time() - arranque) * 1000),
                               "tokens": dato.get("eval_count") or piezas,
                               "modelo": dato.get("model") or modelo or MODELO_CHAT}
                        return
        # El servidor cerró sin marcar `done`: se declara en vez de dejar
        # que parezca una respuesta terminada.
        yield {"tipo": "error",
               "texto": "El modelo cortó la respuesta antes de terminar."}
    finally:
        _en_uso.update(usuario=None, desde=None)
        _turno.release()


def completar(mensajes: list[dict], modelo: str | None = None,
              temperatura: float = 0.3) -> str:
    """La respuesta completa, para usos internos cortos como titular una
    conversación. Consume el mismo streaming: un solo camino de generación."""
    partes = []
    for e in conversar(mensajes, modelo, temperatura, usuario="sistema"):
        if e["tipo"] == "texto":
            partes.append(e["texto"])
    return "".join(partes).strip()
