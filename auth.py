"""
Contraseñas y tokens de sesión. Funciones puras: no tocan la base ni
saben qué es un usuario, así que se prueban sin levantar nada.

Se usa `hashlib.scrypt` de la librería estándar en vez de bcrypt/passlib
-- una dependencia menos que instalar en cada servidor, para algo que
Python ya trae y que es un algoritmo adecuado para contraseñas (lento y
costoso en memoria a propósito).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

# n=16384 con r=8 pide ~16 MB por verificación: suficiente para que
# probar contraseñas por fuerza bruta sea caro, y despreciable para un
# login ocasional.
_N, _R, _P, _LARGO = 16384, 8, 1, 32

LARGO_MINIMO_CLAVE = 8


def hash_clave(clave: str) -> str:
    """Devuelve 'scrypt$n$r$p$salt$hash'. El formato lleva sus propios
    parámetros para poder subirlos en el futuro sin invalidar los hashes
    ya guardados."""
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=_LARGO)
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${h.hex()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    """Compara en tiempo constante. Nunca lanza: un hash con formato
    inesperado es simplemente una contraseña que no coincide."""
    try:
        algo, n, r, p, sal_hex, hash_hex = guardado.split("$")
        if algo != "scrypt":
            return False
        h = hashlib.scrypt(clave.encode(), salt=bytes.fromhex(sal_hex),
                           n=int(n), r=int(r), p=int(p),
                           dklen=len(hash_hex) // 2)
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False


def nuevo_token() -> str:
    """Token de sesión que viaja en la cookie. 32 bytes de entropía."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Lo que se guarda en la base. No lleva sal ni es lento a propósito:
    el token ya es aleatorio y largo, así que no hay nada que adivinar --
    el punto es que quien lea la tabla no pueda usar las sesiones."""
    return hashlib.sha256(token.encode()).hexdigest()


def problema_con_clave(clave: str) -> str | None:
    """Validación mínima. Devuelve el problema, o None si está bien."""
    if len(clave or "") < LARGO_MINIMO_CLAVE:
        return f"La contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres."
    return None
