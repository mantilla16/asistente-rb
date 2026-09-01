"""
Alta del primer administrador, desde el servidor.

La administración de usuarios vive en la web, pero alguien tiene que
poder entrar la primera vez. Este script resuelve ese arranque, y de paso
sirve para recuperar el acceso si se pierde la contraseña del admin.

    python usuarios.py crear
    python usuarios.py clave <usuario>
    python usuarios.py listar

La contraseña se pide de forma oculta: no se pasa como argumento para que
no quede en el historial del shell ni en la lista de procesos.
"""
from __future__ import annotations

import getpass
import sys

import auth
import db


def _pedir_clave() -> str:
    while True:
        clave = getpass.getpass("Contraseña: ")
        problema = auth.problema_con_clave(clave)
        if problema:
            print(problema)
            continue
        if clave != getpass.getpass("Repetir contraseña: "):
            print("No coinciden.")
            continue
        return clave


def crear() -> None:
    usuario = input("Usuario (para entrar): ").strip()
    if not usuario:
        sys.exit("Usuario vacío.")
    if db.usuario_por_nombre(usuario):
        sys.exit(f"El usuario {usuario} ya existe.")
    nombre = input("Nombre completo: ").strip() or usuario
    correo = input("Correo (opcional): ").strip() or None
    rol = (input("Rol [ADMIN]: ").strip() or "ADMIN").upper()
    if rol not in ("ADMIN", "MIEMBRO"):
        sys.exit("Rol debe ser ADMIN o MIEMBRO.")

    db.crear_usuario(usuario, nombre, correo, auth.hash_clave(_pedir_clave()), rol)
    print(f"Creado {usuario} con rol {rol}.")


def clave(usuario: str) -> None:
    u = db.usuario_por_nombre(usuario)
    if not u:
        sys.exit(f"No existe el usuario {usuario}.")
    db.actualizar_usuario(u["id"], clave_hash=auth.hash_clave(_pedir_clave()))
    db.borrar_sesiones_de(u["id"])   # las sesiones abiertas dejan de servir
    print(f"Contraseña de {usuario} actualizada. Sus sesiones se cerraron.")


def listar() -> None:
    filas = db.usuarios()
    if not filas:
        print("No hay usuarios. Cree el primero con: python usuarios.py crear")
        return
    for u in filas:
        estado = "activo" if u["activo"] else "INACTIVO"
        print(f"{u['usuario']:<20} {u['rol']:<8} {estado:<9} {u['nombre']}")


if __name__ == "__main__":
    orden = sys.argv[1] if len(sys.argv) > 1 else ""
    db.abrir()
    try:
        if orden == "crear":
            crear()
        elif orden == "clave" and len(sys.argv) > 2:
            clave(sys.argv[2])
        elif orden == "listar":
            listar()
        else:
            print(__doc__)
    finally:
        db.cerrar()
