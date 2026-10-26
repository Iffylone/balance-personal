"""Sincronización automática PC <-> celular a través de la nube (Supabase).

Cómo funciona (resumen):
- Cada registro (movimiento, cuenta, deuda) tiene un identificador único (uid) que
  se guarda en una tabla lateral (sync_mapa); las tablas del sistema NO se modifican.
- Cada vez que se sincroniza se detectan los cambios locales (nuevos, editados,
  borrados), se suben a la nube y se bajan los cambios de los otros dispositivos.
- Si el mismo registro se cambió en dos lugares, gana el cambio más reciente.
- Las transferencias entre cuentas se mantienen enlazadas (transferencia_uid).
Los datos viajan por HTTPS y cada usuario solo puede ver los suyos (RLS en Supabase).
"""
import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

import db

TABLAS = ("movimientos", "cuentas", "cuentas_por_pagar")
CLAVES_CONFIG = ("admin_user", "admin_hash", "admin_salt", "recovery_hash", "recovery_salt")
LOTE = 200


class ErrorNube(Exception):
    pass


def ahora_ts():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------- esquema / estado
def _asegurar_esquema(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS sync_estado (clave TEXT PRIMARY KEY, valor TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sync_mapa ("
        " tabla TEXT NOT NULL, local_id TEXT NOT NULL, uid TEXT NOT NULL, hash TEXT,"
        " mod_ts TEXT, payload TEXT, enviado INTEGER NOT NULL DEFAULT 0,"
        " borrado INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (tabla, local_id))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_sync_uid ON sync_mapa (tabla, uid)")
    conn.commit()


def _conn():
    conn = db.get_connection()
    _asegurar_esquema(conn)
    return conn


def get_estado(clave, default=None):
    conn = _conn()
    try:
        r = conn.execute("SELECT valor FROM sync_estado WHERE clave=?", (clave,)).fetchone()
        return r["valor"] if r else default
    finally:
        conn.close()


def set_estado(clave, valor):
    conn = _conn()
    try:
        if valor is None:
            conn.execute("DELETE FROM sync_estado WHERE clave=?", (clave,))
        else:
            conn.execute("INSERT INTO sync_estado (clave, valor) VALUES (?,?) "
                         "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (clave, str(valor)))
        conn.commit()
    finally:
        conn.close()


def configurado():
    return bool(get_estado("nube_refresh") and get_estado("nube_url"))


def datos_conexion():
    return {"url": get_estado("nube_url", ""), "key": get_estado("nube_key", ""),
            "email": get_estado("nube_email", "")}


def codigo_para_celular():
    """Texto corto que se pega en el celular para no escribir la clave larga a mano."""
    d = datos_conexion()
    raw = json.dumps({"u": d["url"], "k": d["key"], "e": d["email"]}, separators=(",", ":")).encode()
    return "BAL1:" + base64.urlsafe_b64encode(raw).decode()


def leer_codigo(texto):
    t = (texto or "").strip()
    if not t.startswith("BAL1:"):
        raise ErrorNube("El código no es válido.")
    try:
        d = json.loads(base64.urlsafe_b64decode(t[5:].encode()).decode())
        return d["u"], d["k"], d.get("e", "")
    except Exception:
        raise ErrorNube("El código no es válido.")


# ---------------------------------------------------------------- HTTP
def _req(metodo, url, cuerpo=None, headers=None, timeout=25):
    data = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8") if cuerpo is not None else None
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=metodo, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8")
            return json.loads(txt) if txt.strip() else None
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(txt)
            msg = j.get("error_description") or j.get("msg") or j.get("message") or txt
        except Exception:
            msg = txt
        raise ErrorNube(f"{msg} (código {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ErrorNube("Sin conexión a internet.")


def _base(url):
    return url.strip().rstrip("/")


def _guardar_sesion(r):
    set_estado("nube_access", r["access_token"])
    set_estado("nube_refresh", r["refresh_token"])
    set_estado("nube_exp", time.time() + int(r.get("expires_in", 3600)))
    set_estado("nube_user", (r.get("user") or {}).get("id") or get_estado("nube_user", ""))


def iniciar_sesion(url, key, email, password, crear=False):
    base = _base(url)
    hdr = {"apikey": key}
    if crear:
        r = _req("POST", f"{base}/auth/v1/signup", {"email": email, "password": password}, hdr)
        if not r or not r.get("access_token"):
            raise ErrorNube("La cuenta se creó pero Supabase pide confirmar el correo. "
                            "Confirmalo (o desactivá 'Confirm email' en Supabase) y tocá Conectar.")
    else:
        r = _req("POST", f"{base}/auth/v1/token?grant_type=password",
                 {"email": email, "password": password}, hdr)
    set_estado("nube_url", base)
    set_estado("nube_key", key)
    set_estado("nube_email", email)
    _guardar_sesion(r)


def _token():
    if time.time() > float(get_estado("nube_exp", "0")) - 60:
        base, key = get_estado("nube_url"), get_estado("nube_key")
        r = _req("POST", f"{base}/auth/v1/token?grant_type=refresh_token",
                 {"refresh_token": get_estado("nube_refresh")}, {"apikey": key})
        _guardar_sesion(r)
    return get_estado("nube_access")


def _hdr():
    return {"apikey": get_estado("nube_key"), "Authorization": "Bearer " + _token()}


def hay_datos_en_nube():
    base = get_estado("nube_url")
    r = _req("GET", f"{base}/rest/v1/sync_records?select=uid&limit=1", headers=_hdr())
    return bool(r)


def desconectar():
    for k in ("nube_access", "nube_refresh", "nube_exp", "nube_user", "nube_seq", "nube_ultima"):
        set_estado(k, None)


# ---------------------------------------------------------------- detección de cambios locales
def _payload_fila(fila, uid_por_id):
    d = {k: fila[k] for k in fila.keys() if k not in ("id", "transferencia_id")}
    if "transferencia_id" in fila.keys():
        tid = fila["transferencia_id"]
        d["transferencia_uid"] = uid_por_id.get(tid) if tid is not None else None
    return d


def _hash(p):
    return hashlib.sha1(json.dumps(p, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _json(p):
    return json.dumps(p, ensure_ascii=False, separators=(",", ":"))


def _escanear(conn):
    ahora = ahora_ts()
    cambios = 0
    for t in TABLAS:
        mapa = {r["local_id"]: r for r in conn.execute(
            "SELECT * FROM sync_mapa WHERE tabla=? AND borrado=0", (t,))}
        filas = conn.execute(f"SELECT * FROM {t}").fetchall()
        ids, uid_por_id = set(), {}
        for f in filas:
            lid = str(f["id"])
            ids.add(lid)
            if lid in mapa:
                uid_por_id[f["id"]] = mapa[lid]["uid"]
            else:
                uid = uuid.uuid4().hex
                uid_por_id[f["id"]] = uid
                conn.execute("INSERT OR REPLACE INTO sync_mapa (tabla, local_id, uid, enviado, borrado) "
                             "VALUES (?,?,?,0,0)", (t, lid, uid))
        for f in filas:
            lid = str(f["id"])
            p = _payload_fila(f, uid_por_id)
            h = _hash(p)
            actual = conn.execute("SELECT hash FROM sync_mapa WHERE tabla=? AND local_id=?", (t, lid)).fetchone()
            if actual["hash"] != h:
                conn.execute("UPDATE sync_mapa SET hash=?, mod_ts=?, payload=?, enviado=0 "
                             "WHERE tabla=? AND local_id=?", (h, ahora, _json(p), t, lid))
                cambios += 1
        for lid in mapa:
            if lid not in ids:  # se borró en este equipo
                conn.execute("UPDATE sync_mapa SET borrado=1, mod_ts=?, enviado=0, payload=NULL "
                             "WHERE tabla=? AND local_id=?", (ahora, t, lid))
                cambios += 1
    # configuración compartida (usuario / contraseña de la app)
    for k in CLAVES_CONFIG:
        r = conn.execute("SELECT valor FROM config WHERE clave=?", (k,)).fetchone()
        if r is None:
            continue
        p = {"valor": r["valor"]}
        h = _hash(p)
        m = conn.execute("SELECT * FROM sync_mapa WHERE tabla='config' AND local_id=?", (k,)).fetchone()
        if m is None:
            conn.execute("INSERT INTO sync_mapa (tabla, local_id, uid, hash, mod_ts, payload, enviado, borrado) "
                         "VALUES ('config',?,?,?,?,?,0,0)", (k, k, h, ahora, _json(p)))
            cambios += 1
        elif m["hash"] != h:
            conn.execute("UPDATE sync_mapa SET hash=?, mod_ts=?, payload=?, enviado=0 "
                         "WHERE tabla='config' AND local_id=?", (h, ahora, _json(p), k))
            cambios += 1
    conn.commit()
    return cambios


# ---------------------------------------------------------------- subir
def _subir(conn):
    base, user = get_estado("nube_url"), get_estado("nube_user")
    pend = conn.execute("SELECT * FROM sync_mapa WHERE enviado=0 AND mod_ts IS NOT NULL").fetchall()
    for i in range(0, len(pend), LOTE):
        lote = pend[i:i + LOTE]
        recs = [{"user_id": user, "tabla": r["tabla"], "uid": r["uid"],
                 "data": json.loads(r["payload"]) if r["payload"] else None,
                 "deleted": bool(r["borrado"]), "mod_ts": r["mod_ts"]} for r in lote]
        _req("POST", f"{base}/rest/v1/sync_records?on_conflict=user_id,tabla,uid", recs,
             dict(_hdr(), Prefer="resolution=merge-duplicates,return=minimal"))
        for r in lote:
            conn.execute("UPDATE sync_mapa SET enviado=1 WHERE tabla=? AND local_id=? AND mod_ts=?",
                         (r["tabla"], r["local_id"], r["mod_ts"]))
        conn.commit()
    conn.execute("DELETE FROM sync_mapa WHERE borrado=1 AND enviado=1")
    conn.commit()
    return len(pend)


# ---------------------------------------------------------------- bajar
def _columnas(conn, tabla):
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})")]


def _aplicar(conn, rec, tocados, tuids):
    t, uid, borrada, mod = rec["tabla"], rec["uid"], rec.get("deleted"), rec["mod_ts"]
    data = rec.get("data") or {}
    m = conn.execute("SELECT * FROM sync_mapa WHERE tabla=? AND uid=?", (t, uid)).fetchone()
    if t == "config":
        if uid not in CLAVES_CONFIG or borrada:
            return 0
        if m is not None and (m["mod_ts"] or "") >= mod:
            return 0
        conn.execute("INSERT INTO config (clave, valor) VALUES (?,?) "
                     "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (uid, str(data.get("valor", ""))))
        conn.execute("INSERT OR REPLACE INTO sync_mapa (tabla, local_id, uid, hash, mod_ts, payload, enviado, borrado) "
                     "VALUES ('config',?,?,?,?,?,1,0)", (uid, uid, _hash({"valor": str(data.get("valor", ""))}), mod,
                                                         _json({"valor": str(data.get("valor", ""))})))
        return 1
    if t not in TABLAS:
        return 0
    cols = [c for c in _columnas(conn, t) if c not in ("id", "transferencia_id")]
    vals = {c: data[c] for c in cols if c in data}

    if borrada:
        if m is not None and not m["borrado"] and mod > (m["mod_ts"] or ""):
            conn.execute(f"DELETE FROM {t} WHERE id=?", (m["local_id"],))
            conn.execute("DELETE FROM sync_mapa WHERE tabla=? AND local_id=?", (t, m["local_id"]))
            return 1
        return 0

    if m is not None and not m["borrado"]:
        if (m["mod_ts"] or "") >= mod:
            return 0  # lo local es igual o más nuevo
        if vals:
            sets = ", ".join(f"{c}=?" for c in vals)
            try:
                conn.execute(f"UPDATE {t} SET {sets} WHERE id=?", (*vals.values(), m["local_id"]))
            except Exception:
                return 0
        conn.execute("UPDATE sync_mapa SET mod_ts=?, payload=?, enviado=1 WHERE tabla=? AND local_id=?",
                     (mod, _json(data), t, m["local_id"]))
        tocados.add((t, m["local_id"]))
        if t == "movimientos":
            tuids[m["local_id"]] = data.get("transferencia_uid")
        return 1

    if m is not None and m["borrado"] and mod <= (m["mod_ts"] or ""):
        return 0  # yo lo borré después: gana mi borrado

    # nuevo (o resucitado por una edición más nueva que mi borrado)
    if m is not None:
        conn.execute("DELETE FROM sync_mapa WHERE tabla=? AND local_id=?", (t, m["local_id"]))
    try:
        cur = conn.execute(f"INSERT INTO {t} ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
                           tuple(vals.values()))
        nuevo = cur.lastrowid
    except Exception:
        if t == "cuentas" and "nombre" in vals:
            # misma cuenta creada en los dos equipos: se unifican bajo el uid de la nube
            ex = conn.execute("SELECT id FROM cuentas WHERE nombre=?", (vals["nombre"],)).fetchone()
            if ex is None:
                return 0
            nuevo = ex["id"]
            conn.execute("UPDATE cuentas SET saldo_inicial=? WHERE id=?", (vals.get("saldo_inicial", 0), nuevo))
            viejo = conn.execute("SELECT uid FROM sync_mapa WHERE tabla='cuentas' AND local_id=?", (str(nuevo),)).fetchone()
            if viejo is not None and viejo["uid"] != uid:
                conn.execute("INSERT OR REPLACE INTO sync_mapa (tabla, local_id, uid, mod_ts, enviado, borrado) "
                             "VALUES ('cuentas',?,?,?,0,1)", ("tomb:" + viejo["uid"], viejo["uid"], ahora_ts()))
            conn.execute("DELETE FROM sync_mapa WHERE tabla='cuentas' AND local_id=?", (str(nuevo),))
        else:
            return 0
    conn.execute("INSERT OR REPLACE INTO sync_mapa (tabla, local_id, uid, hash, mod_ts, payload, enviado, borrado) "
                 "VALUES (?,?,?,NULL,?,?,1,0)", (t, str(nuevo), uid, mod, _json(data)))
    tocados.add((t, str(nuevo)))
    if t == "movimientos":
        tuids[str(nuevo)] = data.get("transferencia_uid")
        if data.get("transferencia_uid") is None:
            try:
                db._upsert_beneficiario(conn, data.get("origen_destino", ""), data.get("tipo", ""),
                                        data.get("categoria", ""), data.get("forma_pago", ""),
                                        data.get("cuenta", ""), data.get("fecha", ""), 1)
            except Exception:
                pass
    return 1


def _cerrar_lote(conn, tocados, tuids):
    # enlazar las dos patas de cada transferencia
    for lid, tuid in tuids.items():
        destino = None
        if tuid is not None:
            r = conn.execute("SELECT local_id FROM sync_mapa WHERE tabla='movimientos' AND uid=? AND borrado=0",
                             (tuid,)).fetchone()
            destino = int(r["local_id"]) if r else None
        conn.execute("UPDATE movimientos SET transferencia_id=? WHERE id=?", (destino, int(lid)))
    # recalcular huellas con lo que quedó realmente en la base (para no re-subir lo recién bajado)
    uid_mov = {int(r["local_id"]): r["uid"] for r in conn.execute(
        "SELECT local_id, uid FROM sync_mapa WHERE tabla='movimientos' AND borrado=0")}
    for t, lid in tocados:
        f = conn.execute(f"SELECT * FROM {t} WHERE id=?", (int(lid),)).fetchone()
        if f is None:
            continue
        p = _payload_fila(f, uid_mov)
        conn.execute("UPDATE sync_mapa SET hash=?, payload=? WHERE tabla=? AND local_id=?",
                     (_hash(p), _json(p), t, lid))


def _bajar(conn):
    base = get_estado("nube_url")
    seq = int(get_estado("nube_seq", "0"))
    aplicados = 0
    while True:
        q = urllib.parse.urlencode({"select": "tabla,uid,data,deleted,mod_ts,seq", "seq": f"gt.{seq}",
                                    "order": "seq.asc", "limit": 500})
        filas = _req("GET", f"{base}/rest/v1/sync_records?{q}", headers=_hdr()) or []
        if not filas:
            break
        tocados, tuids = set(), {}
        for rec in filas:
            aplicados += _aplicar(conn, rec, tocados, tuids)
            seq = max(seq, int(rec["seq"]))
        _cerrar_lote(conn, tocados, tuids)
        conn.commit()
        set_estado("nube_seq", seq)
        if len(filas) < 500:
            break
    return aplicados


# ---------------------------------------------------------------- API pública
def reemplazar_local_con_nube():
    """Primer uso en un equipo que ya tenía datos: se descartan y se baja todo de la nube."""
    conn = _conn()
    try:
        for t in ("movimientos", "cuentas", "cuentas_por_pagar", "beneficiarios", "sync_mapa"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()
    set_estado("nube_seq", 0)


def sincronizar_una_vez():
    """Detecta cambios locales, sube, baja. Devuelve {'subidos', 'aplicados', 'error'}."""
    if not configurado():
        return {"subidos": 0, "aplicados": 0, "error": "No está conectado a la nube."}
    conn = _conn()
    try:
        _escanear(conn)
        subidos = _subir(conn)
        aplicados = _bajar(conn)
        set_estado("nube_ultima", time.strftime("%H:%M"))
        return {"subidos": subidos, "aplicados": aplicados, "error": None}
    except ErrorNube as e:
        return {"subidos": 0, "aplicados": 0, "error": str(e)}
    finally:
        conn.close()


SQL_SUPABASE = """-- Ejecutar UNA vez en Supabase: SQL Editor > New query > pegar > Run
create sequence if not exists sync_seq;
create table if not exists public.sync_records (
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  tabla   text not null,
  uid     text not null,
  data    jsonb,
  deleted boolean not null default false,
  mod_ts  text not null,
  seq     bigint not null default nextval('sync_seq'),
  primary key (user_id, tabla, uid)
);
create index if not exists sync_records_seq on public.sync_records (user_id, seq);
alter table public.sync_records enable row level security;
drop policy if exists "solo lo propio" on public.sync_records;
create policy "solo lo propio" on public.sync_records for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create or replace function public.sync_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE' then
    if new.mod_ts <= old.mod_ts then return null; end if;  -- gana el cambio más nuevo
    new.seq := nextval('sync_seq');
  end if;
  return new;
end $$;
drop trigger if exists sync_guard on public.sync_records;
create trigger sync_guard before update on public.sync_records
  for each row execute function public.sync_guard();
"""
