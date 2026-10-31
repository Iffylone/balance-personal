import hashlib
import hmac
import os
import secrets
import time

import db


# ---------------- contraseña de administrador ----------------
def _hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h, salt


def crear_admin(usuario, password):
    h, salt = _hash_password(password)
    db.set_config("admin_user", usuario)
    db.set_config("admin_hash", h)
    db.set_config("admin_salt", salt)


def verificar_login(usuario, password):
    admin_user = db.get_config("admin_user")
    admin_hash = db.get_config("admin_hash")
    admin_salt = db.get_config("admin_salt")
    if usuario != admin_user or admin_hash is None:
        return False
    h, _ = _hash_password(password, admin_salt)
    return hmac.compare_digest(h, admin_hash)


def cambiar_password(nueva_password):
    usuario = db.get_config("admin_user")
    crear_admin(usuario, nueva_password)


# ---------------- clave de recuperación ----------------
# Se genera una clave aleatoria (64 bits) que se muestra UNA sola vez. En la
# base de datos solo queda su hash: nadie (ni este programa) puede volver a
# mostrarla. Si se pierde la contraseña, esa clave es lo único que permite
# crear una nueva sin perder los datos. Cada vez que se usa se genera otra.
_MAX_INTENTOS = 5
_BLOQUEO_SEG = 60
_intentos_fallidos = 0
_bloqueado_hasta = 0.0


def _normalizar_clave(clave):
    return "".join(ch for ch in (clave or "").upper() if ch.isalnum())


def _hash_clave(clave_normalizada, salt):
    return hashlib.pbkdf2_hmac("sha256", clave_normalizada.encode("utf-8"),
                               bytes.fromhex(salt), 120_000).hex()


def tiene_clave_recuperacion():
    return db.get_config("recovery_hash") is not None


def generar_clave_recuperacion():
    """Crea una clave nueva (invalida la anterior) y la devuelve en texto
    legible, formato XXXX-XXXX-XXXX-XXXX. Es la única vez que existe en claro."""
    cruda = secrets.token_hex(8).upper()
    salt = os.urandom(16).hex()
    db.set_config("recovery_salt", salt)
    db.set_config("recovery_hash", _hash_clave(cruda, salt))
    return "-".join(cruda[i:i + 4] for i in range(0, 16, 4))


def segundos_bloqueado():
    return max(0, int(_bloqueado_hasta - time.time()))


def verificar_clave_recuperacion(clave):
    """True/False. Tras 5 intentos fallidos seguidos bloquea 60 segundos."""
    global _intentos_fallidos, _bloqueado_hasta
    if segundos_bloqueado() > 0:
        return False
    h = db.get_config("recovery_hash")
    salt = db.get_config("recovery_salt")
    if not h or not salt:
        return False
    ok = hmac.compare_digest(_hash_clave(_normalizar_clave(clave), salt), h)
    if ok:
        _intentos_fallidos = 0
    else:
        _intentos_fallidos += 1
        if _intentos_fallidos >= _MAX_INTENTOS:
            _bloqueado_hasta = time.time() + _BLOQUEO_SEG
            _intentos_fallidos = 0
    return ok


def restablecer_con_clave(clave, nueva_password):
    """Cambia la contraseña si la clave es correcta. Devuelve la clave NUEVA
    (la usada queda invalidada) o None si la clave no era válida."""
    if not verificar_clave_recuperacion(clave):
        return None
    cambiar_password(nueva_password)
    return generar_clave_recuperacion()
