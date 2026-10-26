import sqlite3
import os
import sys
import json
import csv
import shutil
import unicodedata
from datetime import datetime, date, timedelta


def _carpeta_persistente():
    """Carpeta donde vive el programa de verdad, para guardar la base de datos
    ahí SIEMPRE — tanto corriendo como script (python main.py) como ya
    empaquetado en un .exe con PyInstaller.

    Un .exe hecho con --onefile se autoextrae a una carpeta temporal cada vez
    que arranca (sys._MEIPASS) y esa carpeta se borra al cerrar el programa.
    Si la base de datos se guardara ahí, cada apertura del .exe empezaría de
    cero. Por eso, cuando el programa está "congelado" (sys.frozen), se usa
    la carpeta donde está el .exe real (sys.executable) en vez de esa carpeta
    temporal.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


DB_PATH = os.path.join(_carpeta_persistente(), "contabilidad.db")


def clave_orden(texto):
    """Clave para ordenar alfabéticamente sin importar mayúsculas ni acentos
    (así 'Árbol' queda junto a 'Arroz' y no al final de la lista)."""
    t = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn").lower().strip()


CAT_TRANSFERENCIA = "Transferencia entre cuentas"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _columna_existe(conn, tabla, columna):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})")]
    return columna in cols


def init_db():
    """Crea las tablas si no existen y migra bases de datos viejas (les agrega
    las columnas nuevas) sin borrar ni un solo movimiento ya cargado."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS config (
            clave TEXT PRIMARY KEY,
            valor TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('ingreso','gasto')),
            categoria TEXT NOT NULL,
            descripcion TEXT,
            origen_destino TEXT,
            forma_pago TEXT DEFAULT '',
            cuenta TEXT DEFAULT '',
            monto REAL NOT NULL,
            creado_en TEXT NOT NULL
        )
    """)
    # Migración: si la tabla ya existía de una versión anterior sin estas
    # columnas, se agregan ahora. Los movimientos ya cargados quedan intactos.
    if not _columna_existe(conn, "movimientos", "forma_pago"):
        cur.execute("ALTER TABLE movimientos ADD COLUMN forma_pago TEXT DEFAULT ''")
    if not _columna_existe(conn, "movimientos", "cuenta"):
        cur.execute("ALTER TABLE movimientos ADD COLUMN cuenta TEXT DEFAULT ''")
    # Transferencias entre cuentas: cada transferencia son 2 movimientos (sale de
    # una cuenta, entra en otra) que comparten este id. NULL = movimiento normal.
    if not _columna_existe(conn, "movimientos", "transferencia_id"):
        cur.execute("ALTER TABLE movimientos ADD COLUMN transferencia_id INTEGER")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cuentas_por_pagar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            acreedor TEXT,
            monto_total REAL NOT NULL,
            monto_pagado REAL NOT NULL DEFAULT 0,
            fecha_vencimiento TEXT,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            creado_en TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cuentas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            saldo_inicial REAL NOT NULL DEFAULT 0,
            creado_en TEXT NOT NULL
        )
    """)
    conn.commit()

    # Migración: instalaciones viejas tenían un único "saldo_inicial" global
    # (guardado en config) y los movimientos no apuntaban a ninguna cuenta.
    # Si esta instalación YA estaba configurada (tiene admin) pero todavía no
    # tiene cuentas, se convierte ese saldo global en una cuenta "Efectivo" y
    # se le asignan los movimientos sueltos, para no perder continuidad.
    # Una instalación nueva (todavía sin admin) no dispara esto: en ese caso
    # es la pantalla de configuración inicial la que crea las cuentas.
    ya_configurado = conn.execute(
        "SELECT 1 FROM config WHERE clave='admin_user'"
    ).fetchone() is not None
    hay_cuentas = conn.execute("SELECT COUNT(*) as c FROM cuentas").fetchone()["c"]
    if ya_configurado and hay_cuentas == 0:
        viejo = conn.execute("SELECT valor FROM config WHERE clave='saldo_inicial'").fetchone()
        saldo_previo = float(viejo["valor"]) if viejo else 0.0
        conn.execute(
            "INSERT INTO cuentas (nombre, saldo_inicial, creado_en) VALUES (?,?,?)",
            ("Efectivo", saldo_previo, datetime.now().isoformat()),
        )
        conn.execute(
            "UPDATE movimientos SET cuenta='Efectivo' WHERE cuenta IS NULL OR cuenta=''"
        )
        conn.commit()

    # Beneficiarios (a quién se paga / de quién se cobra): tabla NUEVA y aditiva.
    # No toca movimientos ni cuentas. Se siembra una sola vez con los nombres
    # que ya estaban cargados en los movimientos existentes.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS beneficiarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clave TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            tipo TEXT DEFAULT '',
            categoria TEXT DEFAULT '',
            forma_pago TEXT DEFAULT '',
            cuenta TEXT DEFAULT '',
            veces INTEGER NOT NULL DEFAULT 0,
            ultimo_uso TEXT DEFAULT ''
        )
    """)
    if conn.execute("SELECT 1 FROM config WHERE clave='beneficiarios_sembrado'").fetchone() is None:
        for m in conn.execute("SELECT * FROM movimientos ORDER BY fecha, id").fetchall():
            _upsert_beneficiario(conn, m["origen_destino"], m["tipo"], m["categoria"],
                                 m["forma_pago"], m["cuenta"], m["fecha"])
        conn.execute("INSERT INTO config (clave, valor) VALUES ('beneficiarios_sembrado','1')")
    _migrar_categorias(conn)
    conn.commit()

    conn.close()


# Plan de categorías contables. Se aplica UNA sola vez sobre los datos viejos,
# con respaldo previo de la base. Después se pueden renombrar/unificar desde
# el botón "Categorías".
MAPA_CATEGORIAS = {
    "gasto": {
        "comida": "Alimentos y bebidas", "kiosko": "Alimentos y bebidas",
        "recarga celular": "Servicios", "internet": "Servicios", "servicio": "Servicios",
        "servicios": "Servicios",
        "trasporte": "Transporte", "transporte": "Transporte",
        "colegio": "Educación",
        "préstamos": "Préstamos y deudas", "préstamo": "Préstamos y deudas",
        "prestamos": "Préstamos y deudas", "prestamo": "Préstamos y deudas",
        "deuda": "Préstamos y deudas",
        "compra": "Compras", "compras": "Compras",
        "otro": "Otros gastos", "otros": "Otros gastos",
    },
    "ingreso": {"transferencia joseph": "Transferencias recibidas"},
}


def _migrar_categorias(conn):
    if conn.execute("SELECT 1 FROM config WHERE clave='categorias_migradas'").fetchone():
        return
    conn.commit()
    hay = conn.execute("SELECT COUNT(*) AS c FROM movimientos").fetchone()["c"]
    if hay:
        try:
            shutil.copyfile(DB_PATH, os.path.join(
                os.path.dirname(DB_PATH), "contabilidad_respaldo_antes_de_categorias.db"))
        except Exception:
            pass
    for tipo, mapa in MAPA_CATEGORIAS.items():
        for viejo, nuevo in mapa.items():
            conn.execute("UPDATE movimientos SET categoria=? WHERE tipo=? AND lower(categoria)=?",
                         (nuevo, tipo, viejo))
            conn.execute("UPDATE beneficiarios SET categoria=? WHERE tipo=? AND lower(categoria)=?",
                         (nuevo, tipo, viejo))
    conn.execute("INSERT INTO config (clave, valor) VALUES ('categorias_migradas','1')")
    conn.commit()


def get_config(clave, default=None):
    conn = get_connection()
    row = conn.execute("SELECT valor FROM config WHERE clave=?", (clave,)).fetchone()
    conn.close()
    return row["valor"] if row else default


def set_config(clave, valor):
    conn = get_connection()
    conn.execute(
        "INSERT INTO config (clave, valor) VALUES (?,?) "
        "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
        (clave, str(valor)),
    )
    conn.commit()
    conn.close()


def is_configured():
    return get_config("admin_user") is not None


# ---------------- MOVIMIENTOS ----------------
def add_movimiento(fecha, tipo, categoria, descripcion, origen_destino, monto,
                    forma_pago="", cuenta=""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO movimientos "
        "(fecha, tipo, categoria, descripcion, origen_destino, forma_pago, cuenta, monto, creado_en) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (fecha, tipo, categoria, descripcion, origen_destino, forma_pago, cuenta,
         monto, datetime.now().isoformat()),
    )
    _upsert_beneficiario(conn, origen_destino, tipo, categoria, forma_pago, cuenta, fecha)
    conn.commit()
    conn.close()


def delete_movimiento(id_):
    conn = get_connection()
    fila = conn.execute("SELECT transferencia_id FROM movimientos WHERE id=?", (id_,)).fetchone()
    if fila is not None and fila["transferencia_id"] is not None:
        # una transferencia siempre se borra completa (las dos patas)
        conn.execute("DELETE FROM movimientos WHERE transferencia_id=?", (fila["transferencia_id"],))
    else:
        conn.execute("DELETE FROM movimientos WHERE id=?", (id_,))
    conn.commit()
    conn.close()


def add_transferencia(fecha, cuenta_origen, cuenta_destino, monto, descripcion=""):
    """Mueve dinero de una cuenta a otra. No es ingreso ni gasto: el total
    disponible no cambia y no entra en reportes ni análisis."""
    if not cuenta_origen or not cuenta_destino:
        raise ValueError("Elegí las dos cuentas.")
    if cuenta_origen == cuenta_destino:
        raise ValueError("La cuenta de origen y la de destino deben ser distintas.")
    if monto <= 0:
        raise ValueError("El monto debe ser mayor a cero.")
    ahora = datetime.now().isoformat()
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO movimientos "
            "(fecha, tipo, categoria, descripcion, origen_destino, forma_pago, cuenta, monto, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (fecha, "gasto", CAT_TRANSFERENCIA, descripcion, f"A: {cuenta_destino}", "", cuenta_origen, monto, ahora),
        )
        tid = cur.lastrowid
        conn.execute("UPDATE movimientos SET transferencia_id=? WHERE id=?", (tid, tid))
        conn.execute(
            "INSERT INTO movimientos "
            "(fecha, tipo, categoria, descripcion, origen_destino, forma_pago, cuenta, monto, creado_en, transferencia_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (fecha, "ingreso", CAT_TRANSFERENCIA, descripcion, f"De: {cuenta_origen}", "", cuenta_destino, monto, ahora, tid),
        )
        conn.commit()
    finally:
        conn.close()
    return tid


def get_movimientos(fecha_desde=None, fecha_hasta=None, tipo=None, categoria=None,
                    incluir_transferencias=False):
    """Por defecto NO incluye las transferencias entre cuentas (no son ingresos
    ni gastos): así reportes, análisis y CSV quedan limpios. La tabla principal
    las pide con incluir_transferencias=True."""
    conn = get_connection()
    query = "SELECT * FROM movimientos WHERE 1=1"
    if not incluir_transferencias:
        query += " AND transferencia_id IS NULL"
    params = []
    if fecha_desde:
        query += " AND fecha >= ?"
        params.append(fecha_desde)
    if fecha_hasta:
        query += " AND fecha <= ?"
        params.append(fecha_hasta)
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
    query += " ORDER BY fecha DESC, id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def get_cuentas_usadas():
    """Cuentas/cajas que ya se usaron antes en algún movimiento, para sugerir
    en el combo en vez de tener que escribirlas de nuevo cada vez."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT cuenta FROM movimientos WHERE cuenta IS NOT NULL AND cuenta <> '' "
        "ORDER BY cuenta"
    ).fetchall()
    conn.close()
    return [r["cuenta"] for r in rows]


def get_categorias_usadas(tipo):
    """Categorías ya cargadas antes para ese tipo (ingreso/gasto), para
    sugerirlas además de las fijas, sin obligar a elegir solo de una lista."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT categoria FROM movimientos WHERE tipo=? AND categoria <> '' "
        "AND transferencia_id IS NULL",
        (tipo,),
    ).fetchall()
    conn.close()
    return sorted((r["categoria"] for r in rows), key=clave_orden)


def update_movimiento(id_, fecha, categoria, descripcion, origen_destino, monto,
                       forma_pago="", cuenta=""):
    conn = get_connection()
    conn.execute(
        "UPDATE movimientos SET fecha=?, categoria=?, descripcion=?, origen_destino=?, "
        "forma_pago=?, cuenta=?, monto=? WHERE id=?",
        (fecha, categoria, descripcion, origen_destino, forma_pago, cuenta, monto, id_),
    )
    t = conn.execute("SELECT tipo FROM movimientos WHERE id=?", (id_,)).fetchone()
    if t:
        _upsert_beneficiario(conn, origen_destino, t["tipo"], categoria, forma_pago,
                             cuenta, fecha, sumar=0)
    conn.commit()
    conn.close()


def get_descripciones_usadas():
    """Descripciones (qué se compró / pagó) ya cargadas, en orden alfabético,
    para autocompletar al escribir."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT descripcion FROM movimientos WHERE descripcion IS NOT NULL "
        "AND TRIM(descripcion) <> '' AND transferencia_id IS NULL"
    ).fetchall()
    conn.close()
    vistos, salida = set(), []
    for r in sorted(rows, key=lambda r: clave_orden(r["descripcion"])):
        d = " ".join(r["descripcion"].split())
        if d.lower() not in vistos:
            vistos.add(d.lower())
            salida.append(d)
    return salida


def get_movimiento(id_):
    conn = get_connection()
    row = conn.execute("SELECT * FROM movimientos WHERE id=?", (id_,)).fetchone()
    conn.close()
    return row


# ---------------- CUENTAS (efectivo, banco, billeteras) ----------------
def add_cuenta(nombre, saldo_inicial=0.0):
    conn = get_connection()
    conn.execute(
        "INSERT INTO cuentas (nombre, saldo_inicial, creado_en) VALUES (?,?,?)",
        (nombre.strip(), saldo_inicial, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_cuentas():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM cuentas ORDER BY id").fetchall()
    conn.close()
    return rows


def get_nombres_cuentas():
    return [c["nombre"] for c in get_cuentas()]


def rename_cuenta(id_, nuevo_nombre, nuevo_saldo_inicial):
    conn = get_connection()
    row = conn.execute("SELECT * FROM cuentas WHERE id=?", (id_,)).fetchone()
    if row is None:
        conn.close()
        return
    viejo_nombre = row["nombre"]
    conn.execute(
        "UPDATE cuentas SET nombre=?, saldo_inicial=? WHERE id=?",
        (nuevo_nombre.strip(), nuevo_saldo_inicial, id_),
    )
    if viejo_nombre != nuevo_nombre.strip():
        # Los movimientos ya cargados con el nombre viejo pasan al nombre
        # nuevo, para no perder el historial de esa cuenta.
        conn.execute(
            "UPDATE movimientos SET cuenta=? WHERE cuenta=?",
            (nuevo_nombre.strip(), viejo_nombre),
        )
    conn.commit()
    conn.close()


def delete_cuenta(id_):
    conn = get_connection()
    conn.execute("DELETE FROM cuentas WHERE id=?", (id_,))
    conn.commit()
    conn.close()


def _saldo_de(conn, nombre, saldo_inicial):
    ingresos = conn.execute(
        "SELECT COALESCE(SUM(monto),0) as s FROM movimientos WHERE tipo='ingreso' AND cuenta=?",
        (nombre,),
    ).fetchone()["s"]
    gastos = conn.execute(
        "SELECT COALESCE(SUM(monto),0) as s FROM movimientos WHERE tipo='gasto' AND cuenta=?",
        (nombre,),
    ).fetchone()["s"]
    return saldo_inicial + ingresos - gastos


def get_saldos_cuentas():
    """Devuelve [(nombre, saldo_inicial, saldo_actual), ...] para cada cuenta
    configurada, más un renglón 'Sin cuenta asignada' si hay movimientos
    viejos que no quedaron ligados a ninguna cuenta existente."""
    conn = get_connection()
    cuentas = conn.execute("SELECT * FROM cuentas ORDER BY id").fetchall()
    resultado = []
    nombres_conocidos = [c["nombre"] for c in cuentas]
    for c in cuentas:
        saldo = _saldo_de(conn, c["nombre"], c["saldo_inicial"])
        resultado.append({"id": c["id"], "nombre": c["nombre"],
                           "saldo_inicial": c["saldo_inicial"], "saldo_actual": saldo})
    # movimientos huérfanos: cuenta vacía o que ya no existe (se borró la cuenta)
    placeholders = ",".join("?" * len(nombres_conocidos)) if nombres_conocidos else "''"
    query_extra = (
        f"SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto ELSE -monto END),0) as s "
        f"FROM movimientos WHERE cuenta IS NULL OR cuenta='' "
        f"OR cuenta NOT IN ({placeholders})"
    )
    huerfano = conn.execute(query_extra, nombres_conocidos).fetchone()["s"]
    conn.close()
    if abs(huerfano) > 0.005:
        resultado.append({"id": None, "nombre": "Sin cuenta asignada",
                           "saldo_inicial": 0.0, "saldo_actual": huerfano})
    return resultado


def get_total_disponible():
    return sum(c["saldo_actual"] for c in get_saldos_cuentas())


def get_valores_cuenta_huerfanos():
    """Agrupa los movimientos cuyo texto de 'cuenta' no coincide con ninguna
    cuenta real que exista hoy (típicamente porque venían de versiones viejas
    con texto libre, ej. 'Efectivo caja', 'Cuenta bancaria'). Sirve para
    reasignarlos en bloque a una cuenta real en vez de uno por uno."""
    conn = get_connection()
    nombres = [c["nombre"] for c in conn.execute("SELECT nombre FROM cuentas").fetchall()]
    placeholders = ",".join("?" * len(nombres)) if nombres else "''"
    query = (
        "SELECT COALESCE(NULLIF(cuenta,''), '(sin especificar)') as valor, "
        "COUNT(*) as cantidad, "
        "SUM(CASE WHEN tipo='ingreso' THEN monto ELSE -monto END) as neto "
        f"FROM movimientos WHERE cuenta IS NULL OR cuenta='' OR cuenta NOT IN ({placeholders}) "
        "GROUP BY valor ORDER BY cantidad DESC"
    )
    rows = conn.execute(query, nombres).fetchall()
    conn.close()
    return rows


def reasignar_cuenta_masivo(valor_viejo, nombre_nuevo):
    """Mueve TODOS los movimientos que tenían ese texto de cuenta (huérfano)
    a una cuenta real existente, de una sola vez."""
    conn = get_connection()
    if valor_viejo == "(sin especificar)":
        conn.execute(
            "UPDATE movimientos SET cuenta=? WHERE cuenta IS NULL OR cuenta=''",
            (nombre_nuevo,),
        )
    else:
        conn.execute(
            "UPDATE movimientos SET cuenta=? WHERE cuenta=?",
            (nombre_nuevo, valor_viejo),
        )
    conn.commit()
    conn.close()


def get_balance():
    saldo_inicial = float(get_config("saldo_inicial", 0) or 0)
    conn = get_connection()
    ingresos = conn.execute(
        "SELECT COALESCE(SUM(monto),0) as s FROM movimientos WHERE tipo='ingreso' AND transferencia_id IS NULL"
    ).fetchone()["s"]
    gastos = conn.execute(
        "SELECT COALESCE(SUM(monto),0) as s FROM movimientos WHERE tipo='gasto' AND transferencia_id IS NULL"
    ).fetchone()["s"]
    conn.close()
    return saldo_inicial + ingresos - gastos, ingresos, gastos, saldo_inicial


def get_totales_por_categoria(tipo):
    conn = get_connection()
    rows = conn.execute(
        "SELECT categoria, SUM(monto) as total FROM movimientos WHERE tipo=? AND transferencia_id IS NULL "
        "GROUP BY categoria ORDER BY total DESC",
        (tipo,),
    ).fetchall()
    conn.close()
    return rows


# ---------------- CUENTAS POR PAGAR (préstamos, deudas, servicios) ----------------
def add_cuenta_pagar(tipo, descripcion, acreedor, monto_total, monto_pagado, fecha_vencimiento):
    conn = get_connection()
    estado = "pagada" if monto_pagado >= monto_total else "pendiente"
    conn.execute(
        "INSERT INTO cuentas_por_pagar "
        "(tipo, descripcion, acreedor, monto_total, monto_pagado, fecha_vencimiento, estado, creado_en) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (tipo, descripcion, acreedor, monto_total, monto_pagado, fecha_vencimiento,
         estado, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_cuentas_pagar(estado=None):
    conn = get_connection()
    query = "SELECT * FROM cuentas_por_pagar WHERE 1=1"
    params = []
    if estado:
        query += " AND estado = ?"
        params.append(estado)
    query += " ORDER BY (estado='pendiente') DESC, fecha_vencimiento IS NULL, fecha_vencimiento ASC, id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def get_cuenta_pagar(id_):
    conn = get_connection()
    row = conn.execute("SELECT * FROM cuentas_por_pagar WHERE id=?", (id_,)).fetchone()
    conn.close()
    return row


def abonar_cuenta_pagar(id_, monto):
    conn = get_connection()
    row = conn.execute("SELECT * FROM cuentas_por_pagar WHERE id=?", (id_,)).fetchone()
    if row is None:
        conn.close()
        return
    nuevo_pagado = row["monto_pagado"] + monto
    nuevo_estado = "pagada" if nuevo_pagado >= row["monto_total"] else "pendiente"
    conn.execute(
        "UPDATE cuentas_por_pagar SET monto_pagado=?, estado=? WHERE id=?",
        (nuevo_pagado, nuevo_estado, id_),
    )
    conn.commit()
    conn.close()


def delete_cuenta_pagar(id_):
    conn = get_connection()
    conn.execute("DELETE FROM cuentas_por_pagar WHERE id=?", (id_,))
    conn.commit()
    conn.close()


def get_total_pendiente():
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(monto_total - monto_pagado),0) as s "
        "FROM cuentas_por_pagar WHERE estado='pendiente'"
    ).fetchone()
    conn.close()
    return row["s"]


# ---------------- RESPALDO / MIGRACIÓN ENTRE PCs ----------------
def export_data(filepath):
    conn = get_connection()
    config_rows = conn.execute("SELECT * FROM config").fetchall()
    mov_rows = conn.execute("SELECT * FROM movimientos").fetchall()
    deuda_rows = conn.execute("SELECT * FROM cuentas_por_pagar").fetchall()
    cuenta_rows = conn.execute("SELECT * FROM cuentas").fetchall()
    conn.close()
    data = {
        "config": {r["clave"]: r["valor"] for r in config_rows},
        "movimientos": [dict(r) for r in mov_rows],
        "cuentas_por_pagar": [dict(r) for r in deuda_rows],
        "cuentas": [dict(r) for r in cuenta_rows],
        "exportado_en": datetime.now().isoformat(),
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def import_data(filepath, modo="fusionar"):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    conn = get_connection()
    if modo == "reemplazar":
        conn.execute("DELETE FROM movimientos")
        conn.execute("DELETE FROM cuentas_por_pagar")
        conn.execute("DELETE FROM cuentas")
        conn.execute("DELETE FROM beneficiarios")
    for k, v in data.get("config", {}).items():
        conn.execute(
            "INSERT INTO config (clave, valor) VALUES (?,?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (k, v),
        )
    for c in data.get("cuentas", []):
        conn.execute(
            "INSERT INTO cuentas (nombre, saldo_inicial, creado_en) VALUES (?,?,?) "
            "ON CONFLICT(nombre) DO UPDATE SET saldo_inicial=excluded.saldo_inicial",
            (c["nombre"], c.get("saldo_inicial", 0),
             c.get("creado_en", datetime.now().isoformat())),
        )
    mapa_tid = {}  # id de transferencia del respaldo -> id nuevo en esta base
    for m in data.get("movimientos", []):
        cur = conn.execute(
            "INSERT INTO movimientos "
            "(fecha, tipo, categoria, descripcion, origen_destino, forma_pago, cuenta, monto, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                m["fecha"], m["tipo"], m["categoria"],
                m.get("descripcion", ""), m.get("origen_destino", ""),
                m.get("forma_pago", ""), m.get("cuenta", ""),
                m["monto"], m.get("creado_en", datetime.now().isoformat()),
            ),
        )
        tid_viejo = m.get("transferencia_id")
        if tid_viejo is not None:
            mapa_tid.setdefault(tid_viejo, cur.lastrowid)
            conn.execute("UPDATE movimientos SET transferencia_id=? WHERE id=?",
                         (mapa_tid[tid_viejo], cur.lastrowid))
    for m in data.get("movimientos", []):
        if m.get("transferencia_id") is not None:
            continue
        _upsert_beneficiario(conn, m.get("origen_destino", ""), m["tipo"], m["categoria"],
                             m.get("forma_pago", ""), m.get("cuenta", ""), m["fecha"])
    for d in data.get("cuentas_por_pagar", []):
        conn.execute(
            "INSERT INTO cuentas_por_pagar "
            "(tipo, descripcion, acreedor, monto_total, monto_pagado, fecha_vencimiento, estado, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                d["tipo"], d["descripcion"], d.get("acreedor", ""),
                d["monto_total"], d.get("monto_pagado", 0),
                d.get("fecha_vencimiento"), d.get("estado", "pendiente"),
                d.get("creado_en", datetime.now().isoformat()),
            ),
        )
    conn.commit()
    conn.close()


def export_csv(filepath, filas):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Fecha", "Tipo", "Categoría", "Descripción", "Origen/Destino",
                    "Forma de pago", "Cuenta", "Monto"])
        for r in filas:
            w.writerow([r["fecha"], r["tipo"], r["categoria"], r["descripcion"],
                        r["origen_destino"], r["forma_pago"], r["cuenta"], r["monto"]])



# ---------------- BENEFICIARIOS (autocompletado de "a quién se paga") ----------------
def _norm(nombre):
    return " ".join((nombre or "").split()).lower()


def _upsert_beneficiario(conn, nombre, tipo, categoria, forma_pago, cuenta, fecha, sumar=1):
    """Guarda/actualiza el beneficiario. Recuerda la última categoría, forma de
    pago y cuenta usadas con él (la más reciente por fecha gana)."""
    limpio = " ".join((nombre or "").split())
    clave = limpio.lower()
    if not clave:
        return
    conn.execute("INSERT OR IGNORE INTO beneficiarios (clave, nombre, veces, ultimo_uso) "
                 "VALUES (?,?,0,'')", (clave, limpio))
    conn.execute("UPDATE beneficiarios SET veces=veces+? WHERE clave=?", (sumar, clave))
    conn.execute("UPDATE beneficiarios SET nombre=?, tipo=?, categoria=?, forma_pago=?, cuenta=?, "
                 "ultimo_uso=? WHERE clave=? AND ?>=ultimo_uso",
                 (limpio, tipo, categoria or "", forma_pago or "", cuenta or "",
                  fecha or "", clave, fecha or ""))


def get_beneficiarios():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM beneficiarios").fetchall()
    conn.close()
    return sorted(rows, key=lambda r: clave_orden(r["nombre"]))  # orden alfabético


def get_beneficiario(nombre):
    conn = get_connection()
    row = conn.execute("SELECT * FROM beneficiarios WHERE clave=?", (_norm(nombre),)).fetchone()
    conn.close()
    return row


def rename_beneficiario(id_, nuevo):
    """Renombra un beneficiario (y el texto en sus movimientos). Si el nuevo
    nombre ya existe, los unifica en uno solo."""
    nuevo = " ".join((nuevo or "").split())
    nk = nuevo.lower()
    conn = get_connection()
    old = conn.execute("SELECT * FROM beneficiarios WHERE id=?", (id_,)).fetchone()
    if not old or not nk:
        conn.close()
        return
    for m in conn.execute("SELECT id, origen_destino FROM movimientos").fetchall():
        if _norm(m["origen_destino"]) == old["clave"]:
            conn.execute("UPDATE movimientos SET origen_destino=? WHERE id=?", (nuevo, m["id"]))
    dest = conn.execute("SELECT * FROM beneficiarios WHERE clave=? AND id<>?", (nk, id_)).fetchone()
    if dest:
        conn.execute("UPDATE beneficiarios SET veces=veces+? WHERE id=?", (old["veces"], dest["id"]))
        conn.execute("DELETE FROM beneficiarios WHERE id=?", (id_,))
    else:
        conn.execute("UPDATE beneficiarios SET clave=?, nombre=? WHERE id=?", (nk, nuevo, id_))
    conn.commit()
    conn.close()


def delete_beneficiario(id_):
    conn = get_connection()
    conn.execute("DELETE FROM beneficiarios WHERE id=?", (id_,))
    conn.commit()
    conn.close()


# ---------------- PROMEDIO DE GASTO DIARIO ----------------
def get_stats_gasto_diario():
    """Promedio = gastos totales / días corridos desde el primer gasto hasta hoy
    (cuenta también los días sin gastos). Incluye abonos a deudas."""
    conn = get_connection()
    rows = conn.execute("SELECT fecha, SUM(monto) AS t FROM movimientos "
                        "WHERE tipo='gasto' AND transferencia_id IS NULL GROUP BY fecha").fetchall()
    conn.close()
    if not rows:
        return {"total": 0.0, "dias": 0, "promedio": 0.0, "prom7": 0.0, "hoy": 0.0}
    por_dia = {r["fecha"]: r["t"] for r in rows}
    hoy = date.today()
    primera = date.fromisoformat(min(por_dia))
    dias = max((hoy - primera).days + 1, 1)
    total = sum(por_dia.values())
    dias7 = min(7, dias)
    suma7 = sum(por_dia.get((hoy - timedelta(days=i)).isoformat(), 0.0) for i in range(7))
    return {"total": total, "dias": dias, "promedio": total / dias,
            "prom7": suma7 / dias7, "hoy": por_dia.get(hoy.isoformat(), 0.0)}


def get_gasto_por_dia(n=14):
    conn = get_connection()
    rows = conn.execute("SELECT fecha, SUM(monto) AS t FROM movimientos "
                        "WHERE tipo='gasto' AND transferencia_id IS NULL GROUP BY fecha").fetchall()
    conn.close()
    por_dia = {r["fecha"]: r["t"] for r in rows}
    hoy = date.today()
    out = []
    for i in range(n - 1, -1, -1):
        dia = hoy - timedelta(days=i)
        out.append((dia, por_dia.get(dia.isoformat(), 0.0)))
    return out


# ---------------- CATEGORÍAS (gestión) ----------------
def get_categorias_resumen():
    conn = get_connection()
    rows = conn.execute("SELECT tipo, categoria, COUNT(*) AS n, SUM(monto) AS total "
                        "FROM movimientos WHERE transferencia_id IS NULL "
                        "GROUP BY tipo, categoria").fetchall()
    conn.close()
    # ingresos primero, y dentro de cada tipo en orden alfabético
    return sorted(rows, key=lambda r: (0 if r["tipo"] == "ingreso" else 1, clave_orden(r["categoria"])))


def rename_categoria(tipo, viejo, nuevo):
    nuevo = " ".join((nuevo or "").split())
    if not nuevo or nuevo == viejo:
        return
    conn = get_connection()
    conn.execute("UPDATE movimientos SET categoria=? WHERE tipo=? AND categoria=?", (nuevo, tipo, viejo))
    conn.execute("UPDATE beneficiarios SET categoria=? WHERE tipo=? AND categoria=?", (nuevo, tipo, viejo))
    conn.commit()
    conn.close()


# ---------------- PROMEDIOS Y EVOLUCIÓN (análisis) ----------------
def _rango_meses(conn, desde, hasta):
    """Cantidad de meses calendario que abarca el período (mínimo 1). Si no se
    indica 'desde', se usa el mes del primer gasto cargado."""
    hoy = date.today()
    h = date.fromisoformat(hasta) if hasta else hoy
    if desde:
        d = date.fromisoformat(desde)
    else:
        r = conn.execute("SELECT MIN(fecha) AS f FROM movimientos WHERE tipo='gasto' AND transferencia_id IS NULL").fetchone()
        d = date.fromisoformat(r["f"]) if r and r["f"] else hoy
    meses = max((h.year - d.year) * 12 + (h.month - d.month) + 1, 1)
    return d, h, meses


def get_promedios_categoria(desde=None, hasta=None, tipo="gasto"):
    """Por categoría: cantidad de movimientos, total, promedio por movimiento,
    promedio mensual y porcentaje del total. Dentro del período indicado."""
    conn = get_connection()
    q = ("SELECT categoria, COUNT(*) AS n, SUM(monto) AS total, AVG(monto) AS prom_mov, "
         "MAX(monto) AS maximo FROM movimientos WHERE tipo=? AND transferencia_id IS NULL")
    params = [tipo]
    if desde:
        q += " AND fecha >= ?"
        params.append(desde)
    if hasta:
        q += " AND fecha <= ?"
        params.append(hasta)
    q += " GROUP BY categoria ORDER BY total DESC"
    rows = conn.execute(q, params).fetchall()
    d, h, meses = _rango_meses(conn, desde, hasta)
    conn.close()
    total_general = sum(r["total"] for r in rows)
    filas = []
    for r in rows:
        filas.append({
            "categoria": r["categoria"], "n": r["n"], "total": r["total"],
            "prom_mov": r["prom_mov"], "maximo": r["maximo"],
            "prom_mensual": r["total"] / meses,
            "pct": (r["total"] / total_general * 100) if total_general else 0.0,
        })
    return {"filas": filas, "meses": meses, "total": total_general, "desde": d, "hasta": h}


def get_resumen_mensual(desde=None, hasta=None, max_meses=12):
    """[(aaaa-mm, ingresos, gastos), ...] en orden cronológico, rellenando con
    ceros los meses sin movimientos. Máximo los últimos 'max_meses'."""
    conn = get_connection()
    q = ("SELECT substr(fecha,1,7) AS ym, tipo, SUM(monto) AS t FROM movimientos "
         "WHERE transferencia_id IS NULL")
    params = []
    if desde:
        q += " AND fecha >= ?"
        params.append(desde)
    if hasta:
        q += " AND fecha <= ?"
        params.append(hasta)
    q += " GROUP BY ym, tipo"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    if not rows:
        return []
    datos = {}
    for r in rows:
        datos.setdefault(r["ym"], {"ingreso": 0.0, "gasto": 0.0})[r["tipo"]] = r["t"]
    hoy = date.today()
    fin = date.fromisoformat(hasta) if hasta else hoy
    inicio_txt = min(datos)
    y, m = int(inicio_txt[:4]), int(inicio_txt[5:7])
    salida = []
    while (y, m) <= (fin.year, fin.month):
        ym = f"{y:04d}-{m:02d}"
        d = datos.get(ym, {"ingreso": 0.0, "gasto": 0.0})
        salida.append((ym, d["ingreso"], d["gasto"]))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return salida[-max_meses:]
