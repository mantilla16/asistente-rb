"""
Acceso a Postgres. Pool de conexiones y consultas, nada más.

Las funciones de aquí no deciden nada: reciben lo que hay que guardar y
devuelven lo que hay guardado. Toda regla —quién puede ver qué, cuándo un
documento está listo, qué fragmentos entran al contexto— vive en los
módulos que las llaman, donde se puede leer seguida.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DSN = os.getenv("ASISTENTE_DSN", "postgresql:///asistente_rb")

pool = ConnectionPool(DSN, min_size=1, max_size=8, open=False)


def abrir() -> None:
    pool.open()


def cerrar() -> None:
    pool.close()


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    with pool.connection() as c:
        c.row_factory = dict_row
        yield c


def uno(sql: str, p: tuple = ()) -> dict | None:
    with conn() as c:
        return c.execute(sql, p).fetchone()


def varios(sql: str, p: tuple = ()) -> list[dict]:
    with conn() as c:
        return c.execute(sql, p).fetchall()


def ejecutar(sql: str, p: tuple = ()) -> None:
    with conn() as c:
        c.execute(sql, p)


# =====================================================================
# USUARIOS Y SESIONES
# =====================================================================

def usuario_por_nombre(usuario: str) -> dict | None:
    return uno("SELECT * FROM app.usuario WHERE usuario=%s", (usuario,))


def usuario(usuario_id: str) -> dict | None:
    return uno("SELECT * FROM app.usuario WHERE id=%s", (usuario_id,))


def usuarios() -> list[dict]:
    return varios(
        """SELECT id, usuario, nombre, correo, rol, activo, creado_en,
                  ultimo_acceso
             FROM app.usuario ORDER BY activo DESC, nombre""")


def crear_usuario(usuario: str, nombre: str, correo: str | None,
                  clave_hash: str, rol: str) -> dict:
    return uno(
        """INSERT INTO app.usuario (usuario, nombre, correo, clave_hash, rol)
           VALUES (%s,%s,%s,%s,%s)
           RETURNING id, usuario, nombre, correo, rol, activo""",
        (usuario, nombre, correo, clave_hash, rol))


def actualizar_usuario(usuario_id: str, **campos: Any) -> dict | None:
    if not campos:
        return usuario(usuario_id)
    sets = ", ".join(f"{k}=%s" for k in campos)
    return uno(
        f"""UPDATE app.usuario SET {sets} WHERE id=%s
            RETURNING id, usuario, nombre, correo, rol, activo""",
        (*campos.values(), usuario_id))


def crear_sesion(token_hash: str, usuario_id: str, horas: int,
                 agente: str | None) -> None:
    ejecutar(
        """INSERT INTO app.sesion (token_hash, usuario_id, expira_en, agente)
           VALUES (%s, %s, now() + make_interval(hours => %s), %s)""",
        (token_hash, usuario_id, horas, agente))


def sesion(token_hash: str) -> dict | None:
    """La sesión con su usuario, solo si sigue viva y el usuario sigue activo.

    Las tres condiciones van juntas en la consulta a propósito: separarlas
    invita a que alguien verifique dos y olvide la tercera.
    """
    return uno(
        """SELECT s.token_hash, u.id AS usuario_id, u.usuario, u.nombre, u.rol
             FROM app.sesion s
             JOIN app.usuario u ON u.id = s.usuario_id
            WHERE s.token_hash=%s AND s.expira_en > now() AND u.activo""",
        (token_hash,))


def borrar_sesion(token_hash: str) -> None:
    ejecutar("DELETE FROM app.sesion WHERE token_hash=%s", (token_hash,))


def borrar_sesiones_de(usuario_id: str) -> None:
    ejecutar("DELETE FROM app.sesion WHERE usuario_id=%s", (usuario_id,))


def purgar_sesiones() -> None:
    ejecutar("DELETE FROM app.sesion WHERE expira_en < now()")


def marcar_acceso(usuario_id: str) -> None:
    ejecutar("UPDATE app.usuario SET ultimo_acceso=now() WHERE id=%s",
             (usuario_id,))


# =====================================================================
# DOCUMENTOS
# =====================================================================

def crear_documento(**d: Any) -> dict:
    cols = list(d)
    ph = ", ".join(["%s"] * len(cols))
    return uno(
        f"""INSERT INTO app.documento ({', '.join(cols)}) VALUES ({ph})
            RETURNING *""",
        tuple(d.values()))


def documento(doc_id: str) -> dict | None:
    return uno("SELECT * FROM app.documento WHERE id=%s", (doc_id,))


def documentos_de(usuario_id: str, incluir_compartidos: bool = True) -> list[dict]:
    """Lo del usuario, más lo que otros compartieron explícitamente."""
    return varios(
        """SELECT d.id, d.nombre, d.tipo, d.bytes, d.estado, d.paginas,
                  d.n_fragmentos, d.caracteres, d.error, d.compartido,
                  d.creado_en, d.propietario_id,
                  u.nombre AS propietario,
                  (d.propietario_id = %s) AS es_mio
             FROM app.documento d
             JOIN app.usuario u ON u.id = d.propietario_id
            WHERE d.propietario_id = %s OR (%s AND d.compartido)
            ORDER BY d.creado_en DESC""",
        (usuario_id, usuario_id, incluir_compartidos))


def documento_por_hash(usuario_id: str, h: str) -> dict | None:
    return uno(
        """SELECT * FROM app.documento
            WHERE propietario_id=%s AND hash_sha256=%s AND estado <> 'ERROR'""",
        (usuario_id, h))


def actualizar_documento(doc_id: str, **campos: Any) -> None:
    if not campos:
        return
    sets = ", ".join(f"{k}=%s" for k in campos)
    ejecutar(f"UPDATE app.documento SET {sets} WHERE id=%s",
             (*campos.values(), doc_id))


def borrar_documento(doc_id: str) -> None:
    ejecutar("DELETE FROM app.documento WHERE id=%s", (doc_id,))


def guardar_fragmentos(doc_id: str, fragmentos: list[dict]) -> int:
    """Los fragmentos de un documento, en un COPY.

    El tsvector se calcula en la base y no en Python: es la misma función
    que usará la búsqueda, así que calcularlo en otro lado sería arriesgar
    que indexar y buscar no coincidan.
    """
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM app.fragmento WHERE documento_id=%s",
                        (doc_id,))
            with cur.copy(
                "COPY app.fragmento (documento_id, orden, pagina, seccion, "
                "texto, caracteres, embedding, modelo_embed) FROM STDIN"
            ) as cp:
                for f in fragmentos:
                    cp.write_row([doc_id, f["orden"], f.get("pagina"),
                                  f.get("seccion"), f["texto"],
                                  len(f["texto"]), f.get("embedding"),
                                  f.get("modelo_embed")])
            cur.execute(
                """UPDATE app.fragmento
                      SET tsv = to_tsvector('spanish', texto)
                    WHERE documento_id=%s""",
                (doc_id,))
        c.commit()
    return len(fragmentos)


def fragmentos_de(doc_ids: list[str]) -> list[dict]:
    """Fragmentos con embedding, para comparar contra la pregunta."""
    if not doc_ids:
        return []
    return varios(
        """SELECT f.id, f.documento_id, f.orden, f.pagina, f.seccion,
                  f.texto, f.embedding, d.nombre AS documento
             FROM app.fragmento f
             JOIN app.documento d ON d.id = f.documento_id
            WHERE f.documento_id = ANY(%s) AND f.embedding IS NOT NULL
            ORDER BY f.documento_id, f.orden""",
        (doc_ids,))


def contar_fragmentos(doc_ids: list[str]) -> int:
    if not doc_ids:
        return 0
    return uno("""SELECT count(*) AS n FROM app.fragmento
                   WHERE documento_id = ANY(%s)""", (doc_ids,))["n"]


def buscar_lexico(doc_ids: list[str], consulta: str, limite: int) -> list[dict]:
    """Búsqueda por palabras. `websearch_to_tsquery` acepta lo que la gente
    escribe de verdad -- comillas, `or`, un `-` para excluir -- sin reventar
    con la puntuación, que es lo que hace `to_tsquery`."""
    if not doc_ids or not consulta.strip():
        return []
    return varios(
        """SELECT f.id, f.documento_id, f.orden, f.pagina, f.seccion,
                  f.texto, d.nombre AS documento,
                  ts_rank(f.tsv, q) AS puntaje
             FROM app.fragmento f
             JOIN app.documento d ON d.id = f.documento_id,
                  websearch_to_tsquery('spanish', %s) AS q
            WHERE f.documento_id = ANY(%s) AND f.tsv @@ q
            ORDER BY puntaje DESC
            LIMIT %s""",
        (consulta, doc_ids, limite))


# =====================================================================
# AGENTES
# =====================================================================

def crear_agente(**d: Any) -> dict:
    cols = list(d)
    ph = ", ".join(["%s"] * len(cols))
    return uno(f"""INSERT INTO app.agente ({', '.join(cols)}) VALUES ({ph})
                   RETURNING *""", tuple(d.values()))


def agente(agente_id: str) -> dict | None:
    return uno("SELECT * FROM app.agente WHERE id=%s", (agente_id,))


def agentes_de(usuario_id: str) -> list[dict]:
    return varios(
        """SELECT a.*, u.nombre AS propietario,
                  (a.propietario_id = %s) AS es_mio,
                  (SELECT count(*) FROM app.agente_documento ad
                    WHERE ad.agente_id = a.id) AS n_documentos
             FROM app.agente a
             JOIN app.usuario u ON u.id = a.propietario_id
            WHERE a.activo AND (a.propietario_id = %s OR a.compartido)
            ORDER BY a.creado_en DESC""",
        (usuario_id, usuario_id))


def actualizar_agente(agente_id: str, **campos: Any) -> None:
    """`actualizado_en` se pone en SQL y no como parámetro: la hora que
    importa es la del servidor de base de datos, no la del proceso que
    manda -- y `now()` como texto no es un timestamp válido."""
    sets = "".join(f"{k}=%s, " for k in campos) + "actualizado_en=now()"
    ejecutar(f"UPDATE app.agente SET {sets} WHERE id=%s",
             (*campos.values(), agente_id))


def documentos_del_agente(agente_id: str) -> list[dict]:
    return varios(
        """SELECT d.id, d.nombre, d.estado, d.n_fragmentos
             FROM app.agente_documento ad
             JOIN app.documento d ON d.id = ad.documento_id
            WHERE ad.agente_id=%s
            ORDER BY d.nombre""",
        (agente_id,))


def fijar_documentos_del_agente(agente_id: str, doc_ids: list[str]) -> None:
    with conn() as c:
        c.execute("DELETE FROM app.agente_documento WHERE agente_id=%s",
                  (agente_id,))
        for d in doc_ids:
            c.execute(
                """INSERT INTO app.agente_documento (agente_id, documento_id)
                   VALUES (%s,%s) ON CONFLICT DO NOTHING""",
                (agente_id, d))
        c.commit()


# =====================================================================
# CONVERSACIONES
# =====================================================================

def crear_conversacion(usuario_id: str, agente_id: str | None,
                       titulo: str) -> dict:
    return uno(
        """INSERT INTO app.conversacion (usuario_id, agente_id, titulo)
           VALUES (%s,%s,%s) RETURNING *""",
        (usuario_id, agente_id, titulo))


def conversacion(conv_id: str) -> dict | None:
    return uno("SELECT * FROM app.conversacion WHERE id=%s", (conv_id,))


def conversaciones_de(usuario_id: str, archivadas: bool = False) -> list[dict]:
    return varios(
        """SELECT c.*, a.nombre AS agente,
                  (SELECT count(*) FROM app.mensaje m
                    WHERE m.conversacion_id = c.id) AS n_mensajes
             FROM app.conversacion c
             LEFT JOIN app.agente a ON a.id = c.agente_id
            WHERE c.usuario_id=%s AND c.archivada=%s
            ORDER BY c.actualizada_en DESC
            LIMIT 200""",
        (usuario_id, archivadas))


def actualizar_conversacion(conv_id: str, **campos: Any) -> None:
    sets = ", ".join(f"{k}=%s" for k in campos)
    ejecutar(f"UPDATE app.conversacion SET {sets}, actualizada_en=now() "
             f"WHERE id=%s", (*campos.values(), conv_id))


def borrar_conversacion(conv_id: str) -> None:
    ejecutar("DELETE FROM app.conversacion WHERE id=%s", (conv_id,))


def borrar_mensaje(mensaje_id: int) -> None:
    ejecutar("DELETE FROM app.mensaje WHERE id=%s", (mensaje_id,))


def mensajes_de(conv_id: str, limite: int = 500) -> list[dict]:
    return varios(
        """SELECT id, rol, texto, citas, modelo, ms, tokens_salida, creado_en
             FROM app.mensaje WHERE conversacion_id=%s
            ORDER BY id LIMIT %s""",
        (conv_id, limite))


def guardar_mensaje(conv_id: str, rol: str, texto: str,
                    citas: list | None = None, modelo: str | None = None,
                    ms: int | None = None,
                    tokens_salida: int | None = None) -> dict:
    fila = uno(
        """INSERT INTO app.mensaje
             (conversacion_id, rol, texto, citas, modelo, ms, tokens_salida)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (conv_id, rol, texto,
         json.dumps(citas) if citas is not None else None,
         modelo, ms, tokens_salida))
    ejecutar("UPDATE app.conversacion SET actualizada_en=now() WHERE id=%s",
             (conv_id,))
    return fila


# =====================================================================
# BITÁCORA
# =====================================================================

def registrar(**d: Any) -> None:
    if "detalle" in d and d["detalle"] is not None:
        d["detalle"] = json.dumps(d["detalle"], default=str)
    cols = list(d)
    ph = ", ".join(["%s"] * len(cols))
    ejecutar(f"INSERT INTO app.bitacora ({', '.join(cols)}) VALUES ({ph})",
             tuple(d.values()))


def bitacora(usuario: str | None = None, accion: str | None = None,
             desde: str | None = None, limite: int = 300) -> list[dict]:
    where, args = ["true"], []
    if usuario:
        where.append("usuario = %s")
        args.append(usuario)
    if accion:
        where.append("accion = %s")
        args.append(accion)
    if desde:
        where.append("creado_en >= %s")
        args.append(desde)
    args.append(limite)
    return varios(
        f"""SELECT * FROM app.bitacora WHERE {' AND '.join(where)}
            ORDER BY creado_en DESC LIMIT %s""", tuple(args))
