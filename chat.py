"""
Orquestación de la conversación.

Arma lo que se le pone delante al modelo y guarda lo que salió. El orden
importa y no es arbitrario:

    instrucciones del sistema
    instrucciones del agente
    fragmentos recuperados
    últimos turnos de la conversación
    la pregunta

Los fragmentos van ANTES del historial porque un modelo pequeño atiende
mejor a lo que está cerca del final, y lo que tiene que dominar la respuesta
es el material recuperado, no lo que se dijo hace diez turnos.

Y una regla que define el producto: **el modelo no puede afirmar sobre los
documentos sin citar**. Un asistente que responde con seguridad sin decir de
dónde lo sacó es peor que uno que dice «no lo encuentro», porque el error se
descubre tarde y con el trabajo ya hecho encima.
"""
from __future__ import annotations

import re
from typing import Iterator

import busqueda
import db
import ia

# Cuántos turnos previos se arrastran. Es un tope de contexto, no de memoria:
# en CPU cada token del historial se paga en tiempo de respuesta, y las
# conversaciones largas rara vez dependen de lo que se dijo al principio.
TURNOS = 6

# Cuántos fragmentos por consulta cuando no hay agente. Bajó de 8 a 4
# después de medir en el servidor de oficina: leer el contexto costaba
# 288 segundos con ocho fragmentos de una tabla. Lo que le cuesta tiempo
# al modelo son los tokens del prompt, y más contexto tapa la señal tanto
# como la aporta.
FRAGMENTOS = 4

SISTEMA = """Eres el asistente interno de Russell Bedford, una firma de auditoría y revisoría fiscal en Colombia. Respondes en español, con precisión y sin rodeos.

Reglas que no puedes romper:

1. Cuando respondas a partir del MATERIAL CONSULTADO, cita el número del fragmento entre corchetes, así: [1], [3]. Cita el fragmento del que salió cada afirmación, no al final del todo.
2. Si el material no contiene la respuesta, dilo con esas palabras: no la deduzcas, no la completes con lo que sabes en general, no la inventes. Decir "eso no está en los documentos que consulté" es una respuesta correcta y útil.
3. No cites un fragmento que no usaste.
4. Si el usuario pregunta algo que no depende de los documentos, respóndelo con tu conocimiento y avisa que no viene del material cargado.
5. No repitas cifras de memoria: transcríbelas del fragmento. Una cifra mal copiada en un contexto contable es un error caro.
6. Sé breve. Responde lo que se preguntó y para. Nada de resúmenes de lo que acabas de decir, ni ofrecimientos de ayuda adicional, ni repetir la pregunta. Si hacen falta más detalles, el usuario los pide."""

INTERRUMPIDA = (
    "\n\n_[Respuesta interrumpida: se cerró la conexión antes de que "
    "el modelo terminara. Lo anterior es lo que alcanzó a generar.]_")

_OCUPADO = ("El modelo está atendiendo otra consulta. En este servidor se "
            "genera una respuesta a la vez; espere a que termine y vuelva a "
            "enviar. Su pregunta no se guardó.")

# Preguntas que piden contar, totalizar o enumerar. El modelo ve una MUESTRA
# de fragmentos -- cuatro de setecientos -- así que no puede responderlas, y
# el problema es que las responde igual: dice "hay 3 cuentas" cuando hay 85,
# con el mismo aplomo y las mismas citas que cuando acierta.
#
# Se detecta por palabra porque es barato y no se equivoca hacia el lado
# peligroso: en el peor caso avisa de más en una pregunta que sí podía
# contestar, y eso no rompe nada.
ENUMERATIVA = re.compile(
    r"\b(cu[aá]nt[oa]s?|cuantos?|cuantas?|tod[oa]s?|list[ae]|listado|"
    r"enumera|enumere|total(es)?|totalice|sum[ae]|sume|sumatoria|"
    r"cuent[ae]|conteo|promedio|m[aá]ximo|m[ií]nimo|complet[oa])\b",
    re.IGNORECASE)

# Pedir un conjunto en plural también es enumerativo, aunque no lleve
# ninguna de las palabras de arriba: "dame las cuentas", "muéstrame los
# artículos". No se incluye "cuentas" suelta en el patrón anterior porque
# en una firma de auditoría aparece en casi toda pregunta, y un aviso que
# salta siempre deja de leerse.
PIDE_CONJUNTO = re.compile(
    r"\b(dame|dime|muestra|mu[eé]strame|indica|ind[ií]came|trae)"
    r"\s+(las|los|todas|todos)\b",
    re.IGNORECASE)

AVISO_MUESTRA = """AVISO SOBRE ESTA PREGUNTA: piden contar, totalizar o enumerar. Tú solo ves una MUESTRA de fragmentos, no el documento completo. No puedes contar, sumar ni listar de forma exhaustiva.

Empieza tu respuesta diciendo que solo puedes hablar de los fragmentos que tienes delante y que el número real casi con seguridad es mayor. Luego di qué encontraste EN ESOS FRAGMENTOS, dejando claro que es una muestra. Nunca des una cifra como si fuera el total."""

SIN_MATERIAL = """No hay material consultable para esta pregunta. Responde con tu conocimiento general y di explícitamente, en la primera línea, que no estás consultando ningún documento cargado."""


def _historial(conv_id: str) -> list[dict]:
    mensajes = db.mensajes_de(conv_id)[-TURNOS * 2:]
    return [{"role": "user" if m["rol"] == "usuario" else "assistant",
             "content": m["texto"]}
            for m in mensajes if m["rol"] in ("usuario", "asistente")]


def armar(usuario_id: str, conv: dict, pregunta: str) -> tuple[list[dict], dict]:
    """Los mensajes para el modelo y el rastro de cómo se armaron."""
    agente = db.agente(conv["agente_id"]) if conv.get("agente_id") else None
    cuantos = int(agente["fragmentos"]) if agente else FRAGMENTOS
    hallado = busqueda.buscar(usuario_id, pregunta, agente, cuantos)

    sistema = SISTEMA
    if agente and (agente.get("instrucciones") or "").strip():
        sistema += ("\n\nINSTRUCCIONES DE ESTE AGENTE (mandan sobre lo anterior "
                    "salvo en las reglas de citación):\n"
                    + agente["instrucciones"].strip())

    mensajes = [{"role": "system", "content": sistema}]
    if hallado["fragmentos"]:
        mensajes.append({
            "role": "system",
            "content": ("MATERIAL CONSULTADO:\n\n"
                        + busqueda.contexto(hallado["fragmentos"]))})
    else:
        mensajes.append({"role": "system", "content": SIN_MATERIAL})

    # El aviso va al final, pegado a la pregunta: un modelo pequeño atiende
    # mucho mejor a lo que tiene cerca del final que a lo que se dijo arriba.
    muestra = bool(hallado["fragmentos"]) and bool((ENUMERATIVA.search(pregunta) or PIDE_CONJUNTO.search(pregunta)))
    if muestra:
        mensajes.append({"role": "system", "content": AVISO_MUESTRA})

    mensajes += _historial(conv["id"])
    mensajes.append({"role": "user", "content": pregunta})
    return mensajes, {**hallado, "agente": agente, "muestra": muestra}


def responder(usuario_id: str, conv_id: str, pregunta: str,
              usuario: str) -> Iterator[dict]:
    """Genera la respuesta y la guarda. Emite eventos para la interfaz.

    El mensaje del usuario se guarda ANTES de generar: si el modelo falla o
    se corta la conexión, la pregunta no se pierde y la conversación queda
    coherente.
    """
    conv = db.conversacion(conv_id)
    if not conv or str(conv["usuario_id"]) != str(usuario_id):
        yield {"tipo": "error", "texto": "La conversación no existe."}
        return

    # Se rechaza ANTES de guardar. Si no, cada clic impaciente deja una
    # pregunta huérfana en la conversación: fue justo lo que pasó al probar,
    # tres veces el mismo mensaje sin una sola respuesta debajo.
    if ia.ocupado():
        yield {"tipo": "ocupado", "texto": _OCUPADO}
        return

    mensaje_usuario = db.guardar_mensaje(conv_id, "usuario", pregunta)
    mensajes, rastro = armar(usuario_id, conv, pregunta)

    citas = [{k: f[k] for k in ("n", "documento_id", "documento", "pagina")}
             for f in rastro["fragmentos"]]
    yield {"tipo": "contexto", "citas": citas, "modo": rastro["modo"],
           "criterio": rastro["criterio"], "documentos": rastro["documentos"],
           "muestra": rastro.get("muestra"), "aviso": rastro["aviso"]}

    agente = rastro["agente"]
    modelo = (agente or {}).get("modelo") or ia.MODELO_CHAT
    temperatura = float((agente or {}).get("temperatura") or 0.3)

    partes: list[str] = []
    ms = tokens = None
    completo = False
    try:
        try:
            for e in ia.conversar(mensajes, modelo, temperatura, usuario):
                if e["tipo"] == "texto":
                    partes.append(e["texto"])
                    yield e
                elif e["tipo"] == "fin":
                    ms, tokens, modelo = e["ms"], e["tokens"], e["modelo"]
                    completo = True
                elif e["tipo"] == "error":
                    yield e
        except ia.ModeloOcupado:
            # Carrera perdida contra otro turno: se deshace la pregunta para
            # no dejarla colgando sin respuesta.
            db.borrar_mensaje(mensaje_usuario["id"])
            yield {"tipo": "ocupado", "texto": _OCUPADO}
            return
    finally:
        # Va en `finally` porque si el usuario recarga la página, el
        # generador se cierra aquí mismo y sin esto la respuesta se perdía
        # entera: quedaba la pregunta sola y nada debajo. Lo generado hasta
        # ese punto es trabajo real de este servidor -- minutos de CPU -- y
        # tirarlo por un F5 no tiene defensa.
        texto = "".join(partes).strip()
        if texto:
            if not completo:
                texto += INTERRUMPIDA
            db.guardar_mensaje(conv_id, "asistente", texto, citas,
                               modelo, ms, tokens)
            if conv["titulo"] == "Nueva conversación":
                db.actualizar_conversacion(conv_id, titulo=_titular(pregunta))

    if not texto:
        yield {"tipo": "error", "texto": "El modelo no devolvió texto."}
        return

    yield {"tipo": "fin", "ms": ms, "tokens": tokens, "modelo": modelo}


def _titular(pregunta: str) -> str:
    """Un título corto, tomado de la pregunta.

    Se recorta en vez de pedírselo al modelo: en CPU eso costaría otra
    generación completa por cada conversación nueva, y el título no vale ese
    tiempo.
    """
    limpio = " ".join(pregunta.split())
    return limpio[:60] + ("…" if len(limpio) > 60 else "")
