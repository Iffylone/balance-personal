"""
Selector de fecha con calendario emergente, hecho solo con tkinter y el módulo
estándar `calendar` (viene con Python, no requiere instalar nada ni internet).

Formato que ve el usuario en pantalla: DD-MM-AAAA.
Formato que se guarda en la base de datos: AAAA-MM-DD (para que ordene y filtre
bien; es compatible con los datos que ya tenías cargados).
"""

import tkinter as tk
import calendar
from datetime import datetime

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
          "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
DIAS = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do"]

# Mismos colores oscuros que el resto de la app (ver PALETA en app.py), para
# que el calendario no sea un cuadro blanco encandilante en medio de la app.
BG = "#12141c"
BG_DIA = "#232838"
FG = "#e4e4ec"
BG_HOY = "#3b6df0"


def iso_a_disp(iso):
    """'AAAA-MM-DD' -> 'DD-MM-AAAA'. Si viene vacío o raro, lo devuelve tal cual."""
    if not iso:
        return ""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        return iso


def disp_a_iso(disp):
    """'DD-MM-AAAA' -> 'AAAA-MM-DD'. Lanza ValueError si el formato está mal."""
    return datetime.strptime(disp.strip(), "%d-%m-%Y").strftime("%Y-%m-%d")


class SelectorFecha(tk.Frame):
    """Campo de fecha de solo lectura + botón que abre un calendario.
    Nada de tipeo manual: se elige el día haciendo clic."""

    def __init__(self, master, fecha_inicial_iso=None, **kwargs):
        super().__init__(master, **kwargs)
        # Nota técnica: el estado "readonly" de Entry en Tk ignora el color de
        # fondo que uno le pida (bug conocido de Tk, "readonlybackground" no
        # se pinta). Por eso el campo queda en estado normal pero bloqueado
        # con una tecla que descarta cualquier tipeo: así el fondo oscuro se
        # aplica de verdad y de todas formas no se puede escribir a mano.
        self.entry = tk.Entry(self, width=12, fg=FG, bg=BG_DIA,
                               insertbackground=FG, disabledforeground=FG,
                               justify="center", relief="sunken", bd=1)
        self.entry.bind("<Key>", lambda e: "break")
        self.entry.bind("<Button-1>", lambda e: (self._abrir(), "break")[1])
        self.entry.pack(side="left", fill="x", expand=True)
        if fecha_inicial_iso:
            self.set_iso(fecha_inicial_iso)
        tk.Button(self, text="📅", command=self._abrir, width=3).pack(side="left", padx=(4, 0))

    def _set_texto(self, texto):
        self.entry.delete(0, tk.END)
        self.entry.insert(0, texto)

    def _abrir(self):
        iso_actual = self.get_iso_o_none()
        base = datetime.strptime(iso_actual, "%Y-%m-%d") if iso_actual else datetime.now()
        PopupCalendario(self, base.year, base.month, base.day, self._on_pick)

    def _on_pick(self, y, m, d):
        self._set_texto(f"{d:02d}-{m:02d}-{y}")

    def limpiar(self):
        self._set_texto("")

    def get_disp(self):
        return self.entry.get().strip()

    def get_iso(self):
        return disp_a_iso(self.get_disp())

    def get_iso_o_none(self):
        try:
            return self.get_iso() if self.get_disp() else None
        except ValueError:
            return None

    def set_iso(self, iso):
        self._set_texto(iso_a_disp(iso))


class PopupCalendario(tk.Toplevel):
    def __init__(self, master, year, month, day, on_pick):
        super().__init__(master)
        self.title("Elegir fecha")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.year, self.month = year, month
        self.on_pick = on_pick

        nav = tk.Frame(self)
        nav.pack(fill="x", padx=6, pady=(8, 2))
        tk.Button(nav, text="<", width=3, command=self._mes_ant).pack(side="left")
        self.lbl_mes = tk.Label(nav, text="", font=("Segoe UI", 11, "bold"), width=18)
        self.lbl_mes.pack(side="left", expand=True)
        tk.Button(nav, text=">", width=3, command=self._mes_sig).pack(side="left")

        self.grid_frame = tk.Frame(self, padx=6, pady=6)
        self.grid_frame.pack()

        tk.Button(self, text="Hoy", command=self._hoy).pack(pady=(0, 8))

        self._dibujar()
        self._centrar_sobre(master.winfo_toplevel())

    def _centrar_sobre(self, padre):
        """Abre el calendario centrado sobre la ventana que lo llamó (y
        siempre dentro de la pantalla), en vez de donde caiga por defecto."""
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        try:
            x = padre.winfo_rootx() + (padre.winfo_width() - w) // 2
            y = padre.winfo_rooty() + (padre.winfo_height() - h) // 2
        except tk.TclError:
            x, y = (sw - w) // 2, (sh - h) // 2
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h - 50))
        self.geometry(f"+{x}+{y}")

    def _hoy(self):
        hoy = datetime.now()
        self.year, self.month = hoy.year, hoy.month
        self._dibujar()

    def _mes_ant(self):
        self.month -= 1
        if self.month == 0:
            self.month, self.year = 12, self.year - 1
        self._dibujar()

    def _mes_sig(self):
        self.month += 1
        if self.month == 13:
            self.month, self.year = 1, self.year + 1
        self._dibujar()

    def _dibujar(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.lbl_mes.config(text=f"{MESES[self.month - 1]} {self.year}")
        for i, d in enumerate(DIAS):
            tk.Label(self.grid_frame, text=d, font=("Segoe UI", 10, "bold"),
                     width=4).grid(row=0, column=i, pady=(0, 4))
        cal = calendar.Calendar(firstweekday=0)
        semanas = cal.monthdayscalendar(self.year, self.month)
        hoy = datetime.now()
        for fila, semana in enumerate(semanas, start=1):
            for col, dia in enumerate(semana):
                if dia == 0:
                    continue
                es_hoy = (dia == hoy.day and self.month == hoy.month and self.year == hoy.year)
                tk.Button(
                    self.grid_frame, text=str(dia), width=4, pady=4, relief="flat",
                    bg=BG_HOY if es_hoy else BG_DIA,
                    fg="white" if es_hoy else FG,
                    activebackground=BG_HOY, activeforeground="white",
                    command=lambda d=dia: self._elegir(d),
                ).grid(row=fila, column=col, padx=1, pady=1)

    def _elegir(self, dia):
        self.on_pick(self.year, self.month, dia)
        self.destroy()
