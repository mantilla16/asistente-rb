"""
Recuperación: qué fragmentos se le ponen delante al modelo.

Es la pieza que decide si el asistente sirve. El modelo no sabe nada del
negocio; responde bien si y solo si el fragmento correcto está en el
contexto. Por eso se buscan por dos caminos distintos y se mezclan:

· POR SIGNIFICADO. Se compara el vector de la pregunta contra el de cada
  fragmento del alcance. Encuentra la respuesta aunque esté dicha con otras
  palabras, que es el caso normal.

· POR PALABRAS. Índice de texto completo en español. Encuentra lo que el
  parecido semántico pierde de forma sistemática: un NIT, un número de
  factura, un nombre propio, un código de cuenta. Un vector promedia el
  sentido de la frase y ahí «901228343» pesa lo mismo que cualquier cifra.

Ninguno de los dos basta solo, y por eso están los dos.

La búsqueda por significado es EXACTA: compara contra todos los fragmentos
del alcance, no contra un subconjunto aproximado. Es viable porque un agente
apunta a decenas de documentos. Cuando el alcance pasa del tope, no se
recorta en silencio: se busca solo por palabras y **la respuesta lo declara**.
"""
from __future__ import annotations

import os

import numpy as np

import db
import ia

# Tope de fragmentos que se comparan de una vez. 20.000 fragmentos de 1.024
# dimensiones son ~80 MB en memoria y unos 20 ms de cálculo: cómodo. Más
# allá, el camino correcto es pgvector, no seguir subiendo esto.
TOPE_EXACTO = int(os.getenv("BUSQUEDA_TOPE", "20000"))


def alcance(usuario_id: str, agente: dict | None) -> tuple[list[str], str]:
    """Qué documentos puede leer esta consulta, y cómo se determinó.

    Un agente con documentos asociados se limita a ellos: es lo que lo hace
    preciso. Sin documentos asociados, o sin agente, se consulta todo lo que
    el usuario puede ver. Nunca se cruza a lo de otro usuario salvo que lo
    haya compartido.
    """
    if agente:
        docs = [d["id"] for d in db.documentos_del_agente(agente["id"])
                if d["estado"] == "LISTO"]
        if docs:
            return docs, "los documentos del agente"

    docs = [d["id"] for d in db.documentos_de(usuario_id)
            if d["estado"] == "LISTO"]
    return docs, ("todos sus documentos" if not agente
                  else "todos sus documentos: el agente no tiene ninguno asociado")


def _coseno(pregunta: list[float], matriz: np.ndarray) -> np.ndarray:
    """Similitud coseno de la pregunta contra cada fila.

    Se normaliza en vez de dividir dentro del bucle: es la misma cuenta,
    hecha una vez. El `1e-12` evita dividir por cero con un fragmento cuyo
    vector salió todo en ceros, que pasa cuando el texto era solo símbolos.
    """
    q = np.asarray(pregunta, dtype=np.float32)
    q /= (np.linalg.norm(q) + 1e-12)
    normas = np.linalg.norm(matriz, axis=1) + 1e-12
    return (matriz @ q) / normas


def buscar(usuario_id: str, consulta: str, agente: dict | None = None,
           cuantos: int = 4) -> dict:
    """Los fragmentos más pertinentes, con el rastro de cómo se eligieron."""
    doc_ids, criterio = alcance(usuario_id, agente)
    aviso = None

    if not doc_ids:
        return {"fragmentos": [], "criterio": criterio, "modo": "sin_documentos",
                "documentos": 0, "aviso":
                "No hay documentos procesados en el alcance de esta consulta."}

    total = db.contar_fragmentos(doc_ids)
    por_significado: dict[int, float] = {}
    filas: dict[int, dict] = {}

    if total <= TOPE_EXACTO:
        candidatos = db.fragmentos_de(doc_ids)
        if candidatos:
            matriz = np.array([c["embedding"] for c in candidatos],
                              dtype=np.float32)
            puntajes = _coseno(ia.embedding(consulta), matriz)
            # argpartition en vez de ordenar todo: solo hacen falta los N
            # mejores, y ordenar 20.000 para quedarse con 8 es trabajo tirado.
            n = min(cuantos * 2, len(candidatos))
            mejores = np.argpartition(-puntajes, n - 1)[:n]
            for i in mejores:
                c = candidatos[int(i)]
                filas[c["id"]] = c
                por_significado[c["id"]] = float(puntajes[int(i)])
        modo = "significado y palabras"
    else:
        modo = "solo palabras"
        aviso = (f"El alcance tiene {total:,} fragmentos, por encima del tope "
                 f"de {TOPE_EXACTO:,} que se comparan por significado. Esta "
                 "consulta se resolvió solo por coincidencia de palabras, así "
                 "que puede haber pasado por alto material pertinente.")

    # --- por palabras
    por_palabras: dict[int, float] = {}
    for f in db.buscar_lexico(doc_ids, consulta, cuantos * 2):
        filas.setdefault(f["id"], f)
        por_palabras[f["id"]] = float(f["puntaje"])

    if not filas:
        return {"fragmentos": [], "criterio": criterio, "modo": modo,
                "documentos": len(doc_ids), "aviso": aviso or
                "Ningún fragmento del alcance se parece a la consulta."}

    # --- mezcla
    # Fusión por rango recíproco: cada lista aporta 1/(60+puesto). Se usa el
    # PUESTO y no el puntaje porque coseno y ts_rank viven en escalas
    # distintas y sumarlos directamente le daría todo el peso a una de las
    # dos sin que se note.
    K = 60
    def rangos(d: dict[int, float]) -> dict[int, float]:
        orden = sorted(d, key=lambda i: -d[i])
        return {fid: 1 / (K + p) for p, fid in enumerate(orden)}

    r1, r2 = rangos(por_significado), rangos(por_palabras)
    combinado = {fid: r1.get(fid, 0) + r2.get(fid, 0) for fid in filas}
    elegidos = sorted(combinado, key=lambda i: -combinado[i])[:cuantos]

    fragmentos = []
    for n, fid in enumerate(elegidos, start=1):
        f = filas[fid]
        fragmentos.append({
            "n": n,
            "id": fid,
            "documento_id": str(f["documento_id"]),
            "documento": f["documento"],
            "pagina": f.get("pagina"),
            "seccion": f.get("seccion"),
            "texto": f["texto"],
            "por_significado": round(por_significado.get(fid, 0), 4) or None,
            "por_palabras": round(por_palabras.get(fid, 0), 4) or None,
        })

    return {"fragmentos": fragmentos, "criterio": criterio, "modo": modo,
            "documentos": len(doc_ids), "aviso": aviso}


def contexto(fragmentos: list[dict]) -> str:
    """El bloque de texto que se le pone al modelo.

    Cada fragmento va numerado y con su origen para que el modelo pueda
    citarlo por número. Sin numerar, un modelo pequeño inventa las citas:
    dice «según el informe» sin que haya forma de saber cuál.
    """
    partes = []
    for f in fragmentos:
        donde = f["documento"]
        if f.get("pagina"):
            donde += f", página {f['pagina']}"
        partes.append(f"[{f['n']}] ({donde})\n{f['texto']}")
    return "\n\n".join(partes)
