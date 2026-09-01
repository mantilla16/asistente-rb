"""
API del Asistente RB.

Un middleware hace de puerta única: exige sesión para todo y deja rastro de
toda escritura. Es a propósito el mismo patrón que en analitica-puc, y por la
misma razón: proteger ruta por ruta con decoradores significa que olvidar uno
deja un hueco silencioso. Aquí la sesión es obligatoria por omisión y las
excepciones están enumeradas en un solo lugar, a la vista.

La pertenencia se verifica en cada ruta, no en el middleware: que alguien
tenga sesión no lo autoriza a leer los documentos de otro. Eso es lo que
sostiene la promesa de aislamiento del producto.
"""
from __future__ import annotations

import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (BackgroundTasks, FastAPI, File, Form, HTTPException,
                     Request, Response, UploadFile)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import auth
import busqueda
import chat
import db
import documentos as D
import ia

COOKIE = "asistente_sesion"
SESION_HORAS = int(os.getenv("SESION_HORAS", "12"))
SESION_SEGURA = os.getenv("SESION_SEGURA", "0") in ("1", "true", "True", "si")
MAX_MB = int(os.getenv("MAX_ARCHIVO_MB", "40"))


@asynccontextmanager
async def ciclo(app: FastAPI):
    db.abrir()
    db.purgar_sesiones()
    yield
    db.cerrar()


app = FastAPI(title="Asistente RB", lifespan=ciclo)

# Rutas que no exigen sesión. Cortas y enumeradas: cada una es una decisión.
ABIERTAS = {"/api/auth/login", "/api/salud", "/api/docs", "/api/openapi.json"}

ACCIONES = [
    ("POST",   r"^/api/auth/login$",              "INGRESO",            "usuario"),
    ("POST",   r"^/api/auth/logout$",             "SALIDA",             "usuario"),
    ("PUT",    r"^/api/auth/clave$",              "CLAVE_CAMBIADA",     "usuario"),
    ("POST",   r"^/api/usuarios$",                "USUARIO_CREADO",     "usuario"),
    ("PUT",    r"^/api/usuarios/[^/]+/clave$",    "CLAVE_REINICIADA",   "usuario"),
    ("PUT",    r"^/api/usuarios/[^/]+$",          "USUARIO_EDITADO",    "usuario"),
    ("POST",   r"^/api/documentos$",              "DOCUMENTO_SUBIDO",   "documento"),
    ("DELETE", r"^/api/documentos/[^/]+$",        "DOCUMENTO_BORRADO",  "documento"),
    ("PUT",    r"^/api/documentos/[^/]+$",        "DOCUMENTO_EDITADO",  "documento"),
    ("POST",   r"^/api/documentos/[^/]+/reprocesar$", "DOCUMENTO_REPROCESADO", "documento"),
    ("POST",   r"^/api/agentes$",                 "AGENTE_CREADO",      "agente"),
    ("PUT",    r"^/api/agentes/[^/]+$",           "AGENTE_EDITADO",     "agente"),
    ("DELETE", r"^/api/agentes/[^/]+$",           "AGENTE_BORRADO",     "agente"),
    ("POST",   r"^/api/conversaciones$",          "CONVERSACION_NUEVA", "conversacion"),
    ("DELETE", r"^/api/conversaciones/[^/]+$",    "CONVERSACION_BORRADA","conversacion"),
    ("POST",   r"/mensajes$",                     "CONSULTA",           "conversacion"),
]


def _accion(metodo: str, ruta: str) -> tuple[str, str | None]:
    for m, patron, accion, entidad in ACCIONES:
        if m == metodo and re.search(patron, ruta):
            return accion, entidad
    return f"{metodo} {ruta}", None


def _ip(request: Request) -> str | None:
    """Detrás de nginx la dirección directa sería siempre 127.0.0.1."""
    return (request.headers.get("x-real-ip")
            or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            or (request.client.host if request.client else None))


@app.middleware("http")
async def puerta(request: Request, call_next):
    ruta = request.url.path
    if not ruta.startswith("/api"):
        return await call_next(request)

    request.state.sesion = None
    if ruta not in ABIERTAS:
        token = request.cookies.get(COOKIE)
        s = db.sesion(auth.hash_token(token)) if token else None
        if not s:
            return JSONResponse({"detail": "Sesión requerida"}, status_code=401)
        request.state.sesion = s

    arranque = time.time()
    respuesta = await call_next(request)

    if request.method in ("POST", "PUT", "DELETE"):
        accion, entidad = _accion(request.method, ruta)
        s = request.state.sesion
        db.registrar(
            usuario=(s or {}).get("usuario") or getattr(request.state, "quien", None),
            accion=accion, entidad=entidad,
            entidad_id=getattr(request.state, "entidad_id", None),
            detalle=getattr(request.state, "detalle", None),
            ip=_ip(request), agente_http=request.headers.get("user-agent"),
            estado=respuesta.status_code,
            ms=int((time.time() - arranque) * 1000))
    return respuesta


def _yo(request: Request) -> dict:
    return request.state.sesion


def _uid(request: Request) -> str:
    return str(request.state.sesion["usuario_id"])


def _admin(request: Request) -> None:
    if request.state.sesion["rol"] != "ADMIN":
        raise HTTPException(403, "Requiere rol de administrador")


# =====================================================================
# SESIÓN
# =====================================================================

class Ingreso(BaseModel):
    usuario: str
    clave: str


class Clave(BaseModel):
    clave_actual: str | None = None
    clave: str


@app.get("/api/salud")
def salud() -> dict:
    return {"ok": True, "ia": ia.disponible()}


@app.post("/api/auth/login")
def login(datos: Ingreso, request: Request, response: Response) -> dict:
    request.state.quien = datos.usuario
    u = db.usuario_por_nombre(datos.usuario)
    # Se verifica el hash incluso si el usuario no existe: sin esto, un
    # usuario inexistente responde al instante y uno real tarda 50 ms, lo que
    # permite averiguar qué cuentas existen midiendo el tiempo.
    guardado = u["clave_hash"] if u else auth.hash_clave("descartar")
    if not auth.verificar_clave(datos.clave, guardado) or not u or not u["activo"]:
        raise HTTPException(401, "Usuario o contraseña incorrectos")

    token = auth.nuevo_token()
    db.crear_sesion(auth.hash_token(token), u["id"], SESION_HORAS,
                    request.headers.get("user-agent"))
    db.marcar_acceso(u["id"])
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax",
                        secure=SESION_SEGURA, max_age=SESION_HORAS * 3600,
                        path="/")
    return {"usuario": u["usuario"], "nombre": u["nombre"], "rol": u["rol"]}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        db.borrar_sesion(auth.hash_token(token))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/yo")
def yo(request: Request) -> dict:
    s = _yo(request)
    return {"usuario": s["usuario"], "nombre": s["nombre"], "rol": s["rol"]}


@app.put("/api/auth/clave")
def cambiar_clave(c: Clave, request: Request) -> dict:
    u = db.usuario(_uid(request))
    if not auth.verificar_clave(c.clave_actual or "", u["clave_hash"]):
        raise HTTPException(400, "La contraseña actual no coincide")
    if p := auth.problema_con_clave(c.clave):
        raise HTTPException(400, p)
    db.actualizar_usuario(u["id"], clave_hash=auth.hash_clave(c.clave))
    return {"ok": True}


# =====================================================================
# USUARIOS
# =====================================================================

class UsuarioNuevo(BaseModel):
    usuario: str
    nombre: str
    correo: str | None = None
    clave: str
    rol: str = "MIEMBRO"


class UsuarioEdicion(BaseModel):
    nombre: str | None = None
    correo: str | None = None
    rol: str | None = None
    activo: bool | None = None


@app.get("/api/usuarios")
def listar_usuarios(request: Request) -> list[dict]:
    _admin(request)
    return db.usuarios()


@app.post("/api/usuarios")
def crear_usuario(u: UsuarioNuevo, request: Request) -> dict:
    _admin(request)
    if db.usuario_por_nombre(u.usuario):
        raise HTTPException(409, f"El usuario {u.usuario} ya existe")
    if p := auth.problema_con_clave(u.clave):
        raise HTTPException(400, p)
    if u.rol not in ("ADMIN", "MIEMBRO"):
        raise HTTPException(400, "Rol debe ser ADMIN o MIEMBRO")
    request.state.detalle = {"usuario": u.usuario, "rol": u.rol}
    return db.crear_usuario(u.usuario, u.nombre, u.correo,
                            auth.hash_clave(u.clave), u.rol)


@app.put("/api/usuarios/{usuario_id}")
def editar_usuario(usuario_id: str, u: UsuarioEdicion, request: Request) -> dict:
    _admin(request)
    campos = {k: v for k, v in u.model_dump().items() if v is not None}
    request.state.entidad_id = usuario_id
    request.state.detalle = campos
    fila = db.actualizar_usuario(usuario_id, **campos)
    if not fila:
        raise HTTPException(404, "El usuario no existe")
    if campos.get("activo") is False:
        db.borrar_sesiones_de(usuario_id)   # desactivar cierra las sesiones
    return fila


@app.put("/api/usuarios/{usuario_id}/clave")
def reiniciar_clave(usuario_id: str, c: Clave, request: Request) -> dict:
    _admin(request)
    if p := auth.problema_con_clave(c.clave):
        raise HTTPException(400, p)
    request.state.entidad_id = usuario_id
    db.actualizar_usuario(usuario_id, clave_hash=auth.hash_clave(c.clave))
    db.borrar_sesiones_de(usuario_id)
    return {"ok": True}


# =====================================================================
# DOCUMENTOS
# =====================================================================

class DocumentoEdicion(BaseModel):
    compartido: bool | None = None
    nombre: str | None = None


def _mi_documento(doc_id: str, usuario_id: str, escribir: bool = False) -> dict:
    d = db.documento(doc_id)
    if not d:
        raise HTTPException(404, "El documento no existe")
    mio = str(d["propietario_id"]) == usuario_id
    if not mio and (escribir or not d["compartido"]):
        raise HTTPException(403, "Ese documento no es suyo")
    return d


@app.get("/api/documentos")
def listar_documentos(request: Request) -> list[dict]:
    return db.documentos_de(_uid(request))


@app.post("/api/documentos")
def subir_documento(request: Request, tareas: BackgroundTasks,
                    archivo: UploadFile = File(...),
                    compartido: bool = Form(False)) -> dict:
    uid = _uid(request)
    datos = archivo.file.read()
    if len(datos) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"El archivo supera {MAX_MB} MB")

    ext = Path(archivo.filename or "").suffix.lower()
    tipo = D.TIPOS.get(ext)
    if not tipo:
        raise HTTPException(400,
                            f"No sé leer archivos {ext or 'sin extensión'}. "
                            f"Acepto: {', '.join(sorted(D.TIPOS))}")

    ruta, h = D.guardar_archivo(datos, archivo.filename)
    if ya := db.documento_por_hash(uid, h):
        # Mismo archivo, mismo dueño: se devuelve el que ya está en vez de
        # duplicar fragmentos y volver a pagar la vectorización.
        request.state.entidad_id = str(ya["id"])
        request.state.detalle = {"nombre": ya["nombre"], "repetido": True}
        return {**{k: ya[k] for k in ("id", "nombre", "estado")},
                "repetido": True}

    doc = db.crear_documento(
        propietario_id=uid, nombre=archivo.filename, archivo=str(ruta),
        tipo=tipo, bytes=len(datos), hash_sha256=h, compartido=compartido)

    # En segundo plano: vectorizar un PDF largo en CPU puede tardar minutos,
    # y dejar la petición HTTP colgada ese tiempo la mata el proxy.
    tareas.add_task(D.procesar, str(doc["id"]))
    request.state.entidad_id = str(doc["id"])
    request.state.detalle = {"nombre": archivo.filename, "tipo": tipo,
                             "bytes": len(datos)}
    return {"id": doc["id"], "nombre": doc["nombre"], "estado": "PENDIENTE",
            "repetido": False}


@app.get("/api/documentos/{doc_id}")
def ver_documento(doc_id: str, request: Request) -> dict:
    return _mi_documento(doc_id, _uid(request))


@app.put("/api/documentos/{doc_id}")
def editar_documento(doc_id: str, d: DocumentoEdicion, request: Request) -> dict:
    _mi_documento(doc_id, _uid(request), escribir=True)
    campos = {k: v for k, v in d.model_dump().items() if v is not None}
    request.state.entidad_id = doc_id
    request.state.detalle = campos
    db.actualizar_documento(doc_id, **campos)
    return db.documento(doc_id)


@app.post("/api/documentos/{doc_id}/reprocesar")
def reprocesar(doc_id: str, request: Request, tareas: BackgroundTasks) -> dict:
    _mi_documento(doc_id, _uid(request), escribir=True)
    request.state.entidad_id = doc_id
    db.actualizar_documento(doc_id, estado="PENDIENTE", error=None)
    tareas.add_task(D.procesar, doc_id)
    return {"ok": True, "estado": "PENDIENTE"}


@app.delete("/api/documentos/{doc_id}")
def borrar_documento(doc_id: str, request: Request) -> dict:
    d = _mi_documento(doc_id, _uid(request), escribir=True)
    request.state.entidad_id = doc_id
    request.state.detalle = {"nombre": d["nombre"]}
    # El fichero en disco NO se borra: puede estar compartido con el registro
    # de otro usuario que subió lo mismo. Se limpia aparte, si hace falta.
    db.borrar_documento(doc_id)
    return {"ok": True}


# =====================================================================
# AGENTES
# =====================================================================

class AgenteEntrada(BaseModel):
    nombre: str
    descripcion: str | None = None
    instrucciones: str = ""
    modelo: str | None = None
    temperatura: float = 0.3
    fragmentos: int = 4
    compartido: bool = False
    documentos: list[str] = []


def _mi_agente(agente_id: str, usuario_id: str, escribir: bool = False) -> dict:
    a = db.agente(agente_id)
    if not a or not a["activo"]:
        raise HTTPException(404, "El agente no existe")
    mio = str(a["propietario_id"]) == usuario_id
    if not mio and (escribir or not a["compartido"]):
        raise HTTPException(403, "Ese agente no es suyo")
    return a


@app.get("/api/agentes")
def listar_agentes(request: Request) -> list[dict]:
    return db.agentes_de(_uid(request))


@app.get("/api/agentes/{agente_id}")
def ver_agente(agente_id: str, request: Request) -> dict:
    a = _mi_agente(agente_id, _uid(request))
    return {**a, "documentos": db.documentos_del_agente(agente_id)}


@app.post("/api/agentes")
def crear_agente(a: AgenteEntrada, request: Request) -> dict:
    uid = _uid(request)
    fila = db.crear_agente(
        propietario_id=uid, nombre=a.nombre, descripcion=a.descripcion,
        instrucciones=a.instrucciones, modelo=a.modelo,
        temperatura=a.temperatura, fragmentos=a.fragmentos,
        compartido=a.compartido)
    _fijar_documentos(str(fila["id"]), a.documentos, uid)
    request.state.entidad_id = str(fila["id"])
    request.state.detalle = {"nombre": a.nombre, "documentos": len(a.documentos)}
    return fila


@app.put("/api/agentes/{agente_id}")
def editar_agente(agente_id: str, a: AgenteEntrada, request: Request) -> dict:
    uid = _uid(request)
    _mi_agente(agente_id, uid, escribir=True)
    db.actualizar_agente(agente_id, nombre=a.nombre, descripcion=a.descripcion,
                         instrucciones=a.instrucciones, modelo=a.modelo,
                         temperatura=a.temperatura, fragmentos=a.fragmentos,
                         compartido=a.compartido)
    _fijar_documentos(agente_id, a.documentos, uid)
    request.state.entidad_id = agente_id
    request.state.detalle = {"nombre": a.nombre, "documentos": len(a.documentos)}
    return db.agente(agente_id)


def _fijar_documentos(agente_id: str, doc_ids: list[str], usuario_id: str) -> None:
    """Solo se asocian documentos que el usuario puede ver. Sin esto,
    conocer un id ajeno bastaría para leer su contenido a través de un
    agente."""
    permitidos = {str(d["id"]) for d in db.documentos_de(usuario_id)}
    db.fijar_documentos_del_agente(
        agente_id, [d for d in doc_ids if d in permitidos])


@app.delete("/api/agentes/{agente_id}")
def borrar_agente(agente_id: str, request: Request) -> dict:
    a = _mi_agente(agente_id, _uid(request), escribir=True)
    request.state.entidad_id = agente_id
    request.state.detalle = {"nombre": a["nombre"]}
    # Se desactiva en vez de borrar: las conversaciones lo referencian y
    # borrarlo les quitaría el contexto de con qué se respondió.
    db.actualizar_agente(agente_id, activo=False)
    return {"ok": True}


# =====================================================================
# CONVERSACIONES
# =====================================================================

class ConversacionNueva(BaseModel):
    agente_id: str | None = None
    titulo: str = "Nueva conversación"


class Pregunta(BaseModel):
    texto: str


def _mi_conversacion(conv_id: str, usuario_id: str) -> dict:
    c = db.conversacion(conv_id)
    if not c:
        raise HTTPException(404, "La conversación no existe")
    if str(c["usuario_id"]) != usuario_id:
        raise HTTPException(403, "Esa conversación no es suya")
    return c


@app.get("/api/conversaciones")
def listar_conversaciones(request: Request, archivadas: bool = False) -> list[dict]:
    return db.conversaciones_de(_uid(request), archivadas)


@app.post("/api/conversaciones")
def nueva_conversacion(c: ConversacionNueva, request: Request) -> dict:
    uid = _uid(request)
    if c.agente_id:
        _mi_agente(c.agente_id, uid)
    fila = db.crear_conversacion(uid, c.agente_id, c.titulo)
    request.state.entidad_id = str(fila["id"])
    return fila


@app.get("/api/conversaciones/{conv_id}")
def ver_conversacion(conv_id: str, request: Request) -> dict:
    c = _mi_conversacion(conv_id, _uid(request))
    a = db.agente(c["agente_id"]) if c["agente_id"] else None
    return {**c, "agente": a and {"id": a["id"], "nombre": a["nombre"]},
            "mensajes": db.mensajes_de(conv_id)}


@app.delete("/api/conversaciones/{conv_id}")
def borrar_conversacion(conv_id: str, request: Request) -> dict:
    _mi_conversacion(conv_id, _uid(request))
    request.state.entidad_id = conv_id
    db.borrar_conversacion(conv_id)
    return {"ok": True}


@app.post("/api/conversaciones/{conv_id}/mensajes")
def preguntar(conv_id: str, p: Pregunta, request: Request) -> StreamingResponse:
    """La respuesta llega en streaming.

    Se emite como SSE porque el navegador puede leerlo mientras llega. En
    CPU una respuesta tarda decenas de segundos: devolverla completa al final
    deja al usuario mirando una pantalla en blanco sin saber si funciona.
    """
    s = _yo(request)
    uid = str(s["usuario_id"])
    _mi_conversacion(conv_id, uid)
    request.state.entidad_id = conv_id
    request.state.detalle = {"caracteres": len(p.texto)}

    import json

    def eventos():
        try:
            for e in chat.responder(uid, conv_id, p.texto, s["usuario"]):
                yield f"data: {json.dumps(e, default=str)}\n\n"
        except Exception as e:      # nunca dejar el flujo abierto en silencio
            yield ("data: " + json.dumps(
                {"tipo": "error", "texto": f"{type(e).__name__}: {e}"}) + "\n\n")
        yield "data: [FIN]\n\n"

    return StreamingResponse(eventos(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# =====================================================================
# ESTADO Y BITÁCORA
# =====================================================================

@app.get("/api/ia/estado")
def estado_ia(request: Request) -> dict:
    return {**ia.config(), **ia.disponible(),
            "tope_busqueda": busqueda.TOPE_EXACTO}


@app.get("/api/bitacora")
def ver_bitacora(request: Request, usuario: str | None = None,
                 accion: str | None = None, desde: str | None = None,
                 limite: int = 300) -> list[dict]:
    _admin(request)
    return db.bitacora(usuario, accion, desde, min(limite, 1000))
