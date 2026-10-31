# -*- coding: utf-8 -*-
"""Busca en tu PC todas las bases de datos (contabilidad.db) y respaldos (.json) del
sistema y muestra cuál tiene la información MÁS NUEVA. No modifica ni borra nada."""
import json
import os
import sqlite3
import sys
from datetime import datetime

SALTAR = {"windows", "program files", "program files (x86)", "programdata", "$recycle.bin",
          "system volume information", "node_modules", ".git", "site-packages", "__pycache__",
          "venv", ".venv", "temp", "tmp"}


def es_candidato(nombre):
    n = nombre.lower()
    if n.startswith("contabilidad") and (n.endswith(".db") or ".db." in n):
        return True
    if n.startswith("respaldo") and (n.endswith(".db") or n.endswith(".json")):
        return True
    return n.endswith(".json") and "contable" in n


def analizar(ruta):
    """(movimientos, cuentas, ultima_fecha) o None si no es un dato del sistema."""
    try:
        if ruta.lower().endswith(".json"):
            with open(ruta, "r", encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict) or "movimientos" not in d:
                return None
            movs = d.get("movimientos", [])
            return len(movs), len(d.get("cuentas", [])), max([m.get("fecha", "") for m in movs] or [""])
        c = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        try:
            n = c.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0]
            k = c.execute("SELECT COUNT(*) FROM cuentas").fetchone()[0]
            f = c.execute("SELECT MAX(fecha) FROM movimientos").fetchone()[0] or ""
        finally:
            c.close()
        return n, k, f
    except Exception:
        return None


def raices():
    if os.name == "nt":
        salida = []
        for letra in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            u = f"{letra}:\\"
            if os.path.exists(u):
                if letra == "C":
                    salida.append(os.path.expanduser("~"))   # en C: solo tu carpeta de usuario
                    if os.path.isdir("C:\\SistContiffy"):
                        salida.append("C:\\SistContiffy")
                else:
                    salida.append(u)
        return salida
    return [os.path.expanduser("~")]


def buscar(lista_raices):
    hallados, vistos = [], set()
    for raiz in lista_raices:
        print(f"Buscando en {raiz} ...", flush=True)
        for carpeta, dirs, archivos in os.walk(raiz):
            dirs[:] = [d for d in dirs if d.lower() not in SALTAR and not d.startswith("_MEI")]
            for a in archivos:
                if not es_candidato(a):
                    continue
                ruta = os.path.join(carpeta, a)
                real = os.path.realpath(ruta)
                if real in vistos:
                    continue
                vistos.add(real)
                info = analizar(ruta)
                if info:
                    hallados.append((ruta, os.path.getmtime(ruta), os.path.getsize(ruta)) + info)
    return hallados


def main():
    destino = sys.argv[1:] or raices()
    hallados = buscar(destino)
    lineas = []
    if not hallados:
        lineas.append("No se encontró ninguna base de datos ni respaldo del sistema.")
    else:
        hallados.sort(key=lambda h: (h[5] or "", h[3]), reverse=True)
        lineas.append(f"Se encontraron {len(hallados)} archivo(s). El de arriba tiene la información MÁS NUEVA.\n")
        lineas.append(f"{'N°':>3}  {'ÚLT.MOV.':<11} {'MOVS':>5} {'CTAS':>4}  {'GUARDADO EL':<17} RUTA")
        for i, (ruta, mt, tam, n, k, ult) in enumerate(hallados, 1):
            u = "-".join(reversed(ult.split("-"))) if ult else "-"
            lineas.append(f"{i:>3}  {u:<11} {n:>5} {k:>4}  {datetime.fromtimestamp(mt).strftime('%d-%m-%Y %H:%M'):<17} {ruta}")
        lineas.append("\nCOMO USARLO: el N° 1 suele ser el bueno. Abrí el sistema, tocá 'Restaurar datos...' y elegí ese archivo.")
        lineas.append("Mirá la columna ÚLT.MOV. (fecha del último movimiento) y MOVS (cantidad): más nuevo y con más movimientos = más completo.")
    texto = "\n".join(lineas)
    print("\n" + texto)
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos_encontrados.txt"), "w", encoding="utf-8") as f:
            f.write(texto)
        print("\n(Esta lista también quedó guardada en datos_encontrados.txt)")
    except OSError:
        pass


if __name__ == "__main__":
    main()
