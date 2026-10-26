import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import tkinter.font as tkfont
from datetime import datetime, date, timedelta
import os
import re
import sys
import threading
import time

import db
import auth
import sync
from calendario import SelectorFecha, iso_a_disp, disp_a_iso

PALETA = {
    "bg": "#12141c",
    "bg_alt": "#1c2030",
    "fg": "#e6e8ef",
    "fg_muted": "#8b92a8",
    "entry_bg": "#232838",
    "select_bg": "#3b6df0",
    "tree_bg": "#171a26",
    "side": "#0d1017",
    "side_hover": "#1a2033",
    "card": "#1b1f2e",
    "line": "#262b40",
}


def dinero(v):
    return f"${v:,.2f}"


def corto(v):
    """12.345 -> 12.3k ; 1.250.000 -> 1.3M (para etiquetas de gráficos)."""
    a = abs(v)
    if a >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"{v / 1_000:.1f}k"
    return f"{v:.0f}"


def mezclar(color, objetivo, t):
    """Mezcla dos colores #rrggbb (t=0 -> color, t=1 -> objetivo). Para hovers."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(objetivo[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_larga():
    h = date.today()
    return f"{_DIAS[h.weekday()]} {h.day} de {_MESES[h.month - 1]} de {h.year}"


class Ventana(tk.Toplevel):
    """Toplevel que SIEMPRE aparece centrada sobre la ventana principal (o en
    el centro de la pantalla si todavía no hay ventana principal visible), y
    nunca más grande que la pantalla. Se usa en vez de tk.Toplevel para todos
    los modales: al llamar a geometry("ANCHOxALTO") calcula solo la posición."""

    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._posicionada = False
        self.after_idle(self._centrar_si_falta)

    def geometry(self, spec=None):
        m = re.fullmatch(r"(\d+)x(\d+)", spec) if isinstance(spec, str) else None
        if not m:
            return super().geometry(spec) if spec is not None else super().geometry()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(int(m.group(1)), sw - 40)
        h = min(int(m.group(2)), sh - 90)
        x, y = self._pos_centrada(w, h, sw, sh)
        self._posicionada = True
        return super().geometry(f"{w}x{h}+{x}+{y}")

    def _pos_centrada(self, w, h, sw, sh):
        x, y = (sw - w) // 2, (sh - h) // 2 - 20
        try:
            padre = self.master.winfo_toplevel() if self.master else None
            if padre is not None and padre.winfo_viewable():
                padre.update_idletasks()
                x = padre.winfo_rootx() + (padre.winfo_width() - w) // 2
                y = padre.winfo_rooty() + (padre.winfo_height() - h) // 2
        except tk.TclError:
            pass
        return max(0, min(x, sw - w)), max(0, min(y, sh - h - 50))

    def _centrar_si_falta(self):
        if self._posicionada:
            return
        try:
            self.update_idletasks()
            self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")
        except tk.TclError:
            pass

CATEGORIAS_GASTO = [
    "Alimentos y bebidas", "Servicios", "Transporte", "Vivienda y hogar", "Salud",
    "Educación", "Préstamos y deudas", "Compras", "Entretenimiento", "Otros gastos",
]
CATEGORIAS_INGRESO = ["Salario cooperativa", "Transferencias recibidas", "Reintegros", "Otros ingresos"]
TIPO_DEUDA_A_CATEGORIA = {"Préstamo": "Préstamos y deudas", "Deuda": "Préstamos y deudas",
                          "Servicio": "Servicios", "Otro": "Otros gastos"}
CATEGORIAS_DEUDA = ["Préstamo", "Deuda", "Servicio", "Otro"]
FORMAS_PAGO = ["Efectivo", "Transferencia", "Tarjeta débito", "Tarjeta crédito",
               "Código QR", "Otro"]

if getattr(sys, "frozen", False):
    # Empaquetado con PyInstaller: los assets (íconos, logo) viajan
    # comprimidos dentro del .exe y se autoextraen a una carpeta temporal
    # (sys._MEIPASS) cada vez que arranca. Eso sí es seguro leerlo de ahí
    # (a diferencia de la base de datos, que necesita la carpeta real).
    ASSETS_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "assets")
else:
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self._aplicar_tema_oscuro()
        self.title("Balance personal")
        # Compacta: nunca a pantalla completa ni más grande que la pantalla.
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1180, sw - 60), min(720, sh - 100)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}")
        self.minsize(min(1000, w), min(620, h))
        self.withdraw()

        self._cargar_iconos()
        db.init_db()
        self.usuario_actual = None
        self._sync_activo = False
        self._sync_res = None
        self._sync_loop = False

        if not db.is_configured():
            self.abrir_setup()
        else:
            self.abrir_login()

    def _aplicar_tema_oscuro(self):
        """Fondo oscuro para toda la app (ventanas, formularios, tablas) en vez
        del blanco por defecto de Tkinter, que encandila. Los botones de color
        (verde, rojo, azul, etc.) quedan igual, esto solo cambia lo que era
        blanco/gris claro por defecto."""
        p = PALETA
        for nombre in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(nombre).configure(family="Segoe UI", size=10)
        self.option_add("*Font", ("Segoe UI", 10))
        self.option_add("*Button.relief", "flat")
        self.option_add("*Button.borderWidth", 0)
        self.option_add("*Button.highlightThickness", 0)
        self.option_add("*Button.cursor", "hand2")
        self.option_add("*Button.padX", 12)
        self.option_add("*Button.padY", 5)
        self.option_add("*Entry.relief", "flat")
        self.option_add("*Entry.borderWidth", 5)
        self.option_add("*Entry.highlightThickness", 1)
        self.option_add("*Entry.highlightBackground", "#2f3550")
        self.option_add("*Entry.highlightColor", p["select_bg"])
        self.option_add("*TCombobox*Listbox.Font", ("Segoe UI", 10))
        self.option_add("*TCombobox*Listbox.Background", p["entry_bg"])
        self.option_add("*TCombobox*Listbox.Foreground", p["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", p["select_bg"])
        self.configure(bg=p["bg"])
        self.option_add("*Background", p["bg"])
        self.option_add("*Foreground", p["fg"])
        self.option_add("*Entry.Background", p["entry_bg"])
        self.option_add("*Entry.Foreground", p["fg"])
        self.option_add("*Entry.insertBackground", p["fg"])
        self.option_add("*Listbox.Background", p["entry_bg"])
        self.option_add("*Listbox.Foreground", p["fg"])
        self.option_add("*Button.Background", p["bg_alt"])
        self.option_add("*Button.Foreground", p["fg"])
        self.option_add("*Button.activeBackground", p["select_bg"])
        self.option_add("*Button.activeForeground", "white")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=p["tree_bg"], fieldbackground=p["tree_bg"],
                         foreground=p["fg"], rowheight=28, font=("Segoe UI", 10), bordercolor=p["bg_alt"])
        style.map("Treeview", background=[("selected", p["select_bg"])],
                   foreground=[("selected", "white")])
        style.configure("Treeview.Heading", background=p["bg_alt"], foreground=p["fg"],
                         relief="flat")
        style.map("Treeview.Heading", background=[("active", p["bg_alt"])])
        style.configure("TCombobox", fieldbackground=p["entry_bg"], background=p["entry_bg"],
                         foreground=p["fg"], arrowcolor=p["fg"])
        style.map("TCombobox", fieldbackground=[("readonly", p["entry_bg"])],
                   foreground=[("readonly", p["fg"])])
        style.configure("TNotebook", background=p["bg"], bordercolor=p["bg_alt"])
        style.configure("TNotebook.Tab", background=p["bg_alt"], foreground=p["fg"], padding=(10, 6))
        style.map("TNotebook.Tab", background=[("selected", p["select_bg"])],
                   foreground=[("selected", "white")])
        style.configure("Vertical.TScrollbar", background="#2a3150", troughcolor=p["bg"],
                         arrowcolor=p["fg_muted"], bordercolor=p["bg"], lightcolor="#2a3150",
                         darkcolor="#2a3150", gripcount=0, relief="flat", arrowsize=13)
        style.map("Vertical.TScrollbar", background=[("active", "#3b6df0")])
        style.configure("TSeparator", background=p["bg_alt"])
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), padding=(8, 6))
        style.configure("Treeview", lightcolor=p["bg"], darkcolor=p["bg"], bordercolor=p["bg"], borderwidth=0)
        style.configure("TCombobox", padding=5, selectbackground=p["entry_bg"], selectforeground=p["fg"])
        style.configure("TNotebook.Tab", font=("Segoe UI", 10), padding=(14, 6))

    def _cargar_iconos(self):
        """Carga el icono de la ventana/taskbar y las imágenes del logo.
        Guarda las referencias en self para que Tkinter no las recolecte."""
        self.img_icon_taskbar = None
        self.img_icon_small = None
        self.img_logo_header = None
        try:
            icono_png = os.path.join(ASSETS_DIR, "icon_192.png")
            if os.path.exists(icono_png):
                self.img_icon_taskbar = tk.PhotoImage(file=icono_png)
                self.iconphoto(True, self.img_icon_taskbar)
            if sys.platform.startswith("win"):
                icono_ico = os.path.join(ASSETS_DIR, "icon.ico")
                if os.path.exists(icono_ico):
                    self.iconbitmap(icono_ico)
        except Exception:
            pass  # si el icono falla, el sistema igual funciona
        try:
            icono_32 = os.path.join(ASSETS_DIR, "icon_32.png")
            if os.path.exists(icono_32):
                self.img_icon_small = tk.PhotoImage(file=icono_32)
        except Exception:
            pass
        try:
            logo_path = os.path.join(ASSETS_DIR, "logo_header.png")
            if os.path.exists(logo_path):
                self.img_logo_header = tk.PhotoImage(file=logo_path)
        except Exception:
            pass
        self.img_logo_front = self._cargar_png("logo_front.png")
        self.img_logo_login = self._cargar_png("logo_login.png")
        self.img_logo_small = self._cargar_png("logo_small.png")

    def _cargar_png(self, nombre):
        try:
            ruta = os.path.join(ASSETS_DIR, nombre)
            if os.path.exists(ruta):
                return tk.PhotoImage(file=ruta)
        except Exception:
            pass
        return None

    # ---------------- CONFIGURACIÓN INICIAL ----------------
    def abrir_setup(self):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Configuración inicial")
        modal.geometry("560x820")
        modal.grab_set()
        modal.resizable(False, False)
        modal.protocol("WM_DELETE_WINDOW", self.destroy)
        if self.img_logo_small:
            tk.Label(modal, image=self.img_logo_small, bg="#0d1017", highlightbackground=PALETA["line"],
                     highlightthickness=1).pack(pady=(14, 0))
        elif self.img_icon_small:
            tk.Label(modal, image=self.img_icon_small).pack(pady=(15, 0))

        tk.Label(modal, text="Configuración inicial", font=("Segoe UI", 15, "bold")).pack(pady=(6, 2))
        tk.Label(modal, text="Creá tu acceso y el saldo con el que arranca cada cuenta.",
                 font=("Segoe UI", 10), fg=PALETA["fg_muted"]).pack(pady=(0, 10))

        frm = tk.Frame(modal, padx=24)
        frm.pack(fill="x")
        frm.grid_columnconfigure(1, weight=1)

        def fila(r, texto, show=None, inicial=None):
            tk.Label(frm, text=texto).grid(row=r, column=0, sticky="w", pady=6, padx=(0, 12))
            e = tk.Entry(frm, width=24, show=show) if show else tk.Entry(frm, width=24)
            if inicial is not None:
                e.insert(0, inicial)
            e.grid(row=r, column=1, pady=6, sticky="ew")
            return e

        e_user = fila(0, "Usuario administrador:")
        e_pass = fila(1, "Contraseña:", show="*")
        e_pass2 = fila(2, "Confirmar contraseña:", show="*")
        ttk.Separator(frm, orient="horizontal").grid(row=3, column=0, columnspan=2,
                                                        sticky="ew", pady=10)
        tk.Label(frm, text="Tus cuentas (efectivo, bancos, billeteras…) y su saldo actual:",
                 font=("Segoe UI", 10, "bold")).grid(row=4, column=0, columnspan=2,
                                                     sticky="w", pady=(0, 4))
        fr_ctas = tk.Frame(frm)
        fr_ctas.grid(row=5, column=0, columnspan=2, sticky="ew")
        fr_ctas.grid_columnconfigure(0, weight=1)
        tk.Label(fr_ctas, text="Nombre de la cuenta", font=("Segoe UI", 9),
                 fg=PALETA["fg_muted"]).grid(row=0, column=0, sticky="w")
        tk.Label(fr_ctas, text="Saldo ($)", font=("Segoe UI", 9),
                 fg=PALETA["fg_muted"]).grid(row=0, column=1, sticky="w")
        filas_ctas = []
        MAX_CTAS = 8

        def agregar_fila(nombre=""):
            if len(filas_ctas) >= MAX_CTAS:
                messagebox.showinfo("Cuentas", f"Podés cargar hasta {MAX_CTAS} cuentas acá. "
                                    "Las demás las agregás después desde 'Gestionar cuentas'.", parent=modal)
                return
            r = len(filas_ctas) + 1
            en = tk.Entry(fr_ctas)
            en.grid(row=r, column=0, sticky="ew", pady=3, padx=(0, 8))
            es = tk.Entry(fr_ctas, width=14)
            es.grid(row=r, column=1, pady=3)
            if nombre:
                en.insert(0, nombre)
            es.insert(0, "0")
            filas_ctas.append((en, es))

        agregar_fila("Efectivo")
        agregar_fila()
        tk.Button(frm, text="+ Agregar otra cuenta", command=lambda: agregar_fila(),
                  bg=PALETA["card"], fg="white", activebackground=PALETA["card"],
                  activeforeground="white", bd=0, padx=10, pady=4).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tk.Label(frm, text="Usá los nombres que quieras. Después podés agregar o cambiar cuentas "
                           "desde 'Gestionar cuentas'.",
                 font=("Segoe UI", 9), fg=PALETA["fg_muted"], justify="left", wraplength=470).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def guardar():
            usuario = e_user.get().strip()
            p1, p2 = e_pass.get(), e_pass2.get()
            if not usuario or not p1:
                messagebox.showerror("Error", "Usuario y contraseña son obligatorios.", parent=modal)
                return
            if p1 != p2:
                messagebox.showerror("Error", "Las contraseñas no coinciden.", parent=modal)
                return
            cuentas_nuevas = []
            for en, es in filas_ctas:
                nombre = " ".join(en.get().split())
                txt = es.get().strip().replace(",", ".")
                if not nombre and txt in ("", "0", "0.0", "0.00"):
                    continue
                if not nombre:
                    messagebox.showerror("Error", "Hay un saldo sin nombre de cuenta.", parent=modal)
                    return
                try:
                    saldo = float(txt) if txt else 0.0
                except ValueError:
                    messagebox.showerror("Error", f"El saldo de '{nombre}' debe ser un número.", parent=modal)
                    return
                cuentas_nuevas.append((nombre, saldo))
            if not cuentas_nuevas:
                messagebox.showerror("Error", "Cargá al menos una cuenta (por ejemplo: Efectivo).", parent=modal)
                return
            if len({n.lower() for n, _ in cuentas_nuevas}) != len(cuentas_nuevas):
                messagebox.showerror("Error", "Hay dos cuentas con el mismo nombre.", parent=modal)
                return
            auth.crear_admin(usuario, p1)
            for nombre, saldo in cuentas_nuevas:
                db.add_cuenta(nombre, saldo)
            clave = auth.generar_clave_recuperacion()
            modal.destroy()
            self._mostrar_clave_recuperacion(clave, on_close=self.abrir_login, inicial=True)

        tk.Button(modal, text="Guardar y continuar", command=guardar,
                  bg="#2FA36B", fg="white", activebackground="#2FA36B", activeforeground="white",
                  font=("Segoe UI", 11, "bold"), padx=24, pady=8).pack(pady=18)

    # ---------------- CLAVE DE RECUPERACIÓN ----------------
    def _mostrar_clave_recuperacion(self, clave, parent=None, on_close=None, inicial=False):
        parent = parent or self
        p = PALETA
        modal = Ventana(parent)
        modal.configure(bg=p["bg"])
        modal.title("Clave de recuperación")
        modal.geometry("540x470")
        modal.transient(parent)
        modal.grab_set()
        modal.resizable(False, False)
        modal.protocol("WM_DELETE_WINDOW", lambda: None)  # solo se cierra con el botón

        tk.Label(modal, text="Tu clave de recuperación", font=("Segoe UI", 15, "bold")).pack(pady=(22, 4))
        if inicial:
            tk.Label(modal, text="Configuración guardada.", fg="#6fd69b",
                     font=("Segoe UI", 10, "bold")).pack()
        tk.Label(modal, wraplength=470, justify="center", fg=p["fg_muted"],
                 text="Si algún día olvidás la contraseña, esta clave es la única forma de entrar "
                      "sin perder tus datos. Anotala en papel o sacale una foto y guardala FUERA de "
                      "esta PC. Por seguridad no se puede volver a mostrar.").pack(pady=(8, 14))

        caja = tk.Frame(modal, bg=p["card"], highlightbackground="#F59E0B", highlightthickness=1)
        caja.pack(padx=40, fill="x")
        tk.Label(caja, text=clave, font=("Consolas", 22, "bold"), bg=p["card"], fg="#F59E0B",
                 pady=16).pack()

        estado = tk.Label(modal, text="", fg="#6fd69b", font=("Segoe UI", 9))

        def copiar():
            self.clipboard_clear()
            self.clipboard_append(clave)
            estado.config(text="Copiada al portapapeles. Pegala en un lugar seguro y borrala de ahí si es necesario.")

        tk.Button(modal, text="Copiar clave", command=copiar, bg=p["bg_alt"], fg=p["fg"],
                  padx=16, pady=6).pack(pady=(12, 2))
        estado.pack()

        var = tk.BooleanVar(value=False)
        boton = tk.Button(modal, text="Continuar", state="disabled", bg="#2b3347", fg="white",
                          disabledforeground="#6b7280", activebackground="#2FA36B",
                          font=("Segoe UI", 11, "bold"), padx=24, pady=8)

        def cerrar():
            modal.destroy()
            if on_close:
                on_close()

        boton.config(command=cerrar)
        tk.Checkbutton(modal, text="Ya la guardé en un lugar seguro", variable=var,
                       command=lambda: boton.config(state="normal" if var.get() else "disabled",
                                                    bg="#2FA36B" if var.get() else "#2b3347"),
                       bg=p["bg"], fg=p["fg"], selectcolor=p["entry_bg"], activebackground=p["bg"],
                       activeforeground=p["fg"], cursor="hand2").pack(pady=(10, 6))
        boton.pack(pady=(4, 10))

    def _recordar_clave_recuperacion(self):
        """Instalaciones anteriores a esta versión no tienen clave: se ofrece
        crearla apenas se entra, porque sin ella no hay forma de recuperar acceso."""
        if auth.tiene_clave_recuperacion():
            return
        if messagebox.askyesno(
            "Clave de recuperación",
            "Este sistema todavía no tiene clave de recuperación.\n\n"
            "Sin ella, si olvidás la contraseña no hay forma de volver a entrar sin perder los datos.\n\n"
            "¿Querés generarla ahora?",
        ):
            self._mostrar_clave_recuperacion(auth.generar_clave_recuperacion())

    # ---------------- LOGIN ----------------
    def abrir_login(self):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Iniciar sesión")
        modal.geometry("440x560")
        modal.grab_set()
        modal.resizable(False, False)
        modal.protocol("WM_DELETE_WINDOW", self.destroy)
        if self.img_logo_login:
            tk.Label(modal, image=self.img_logo_login, bg="#0d1017", highlightbackground=PALETA["line"],
                     highlightthickness=1).pack(pady=(22, 0))
        elif self.img_icon_small:
            tk.Label(modal, image=self.img_icon_small).pack(pady=(15, 0))

        tk.Label(modal, text="Balance personal", font=("Segoe UI", 17, "bold")).pack(pady=(4, 0))
        tk.Label(modal, text="Acceso administrador", font=("Segoe UI", 10),
                 fg=PALETA["fg_muted"]).pack(pady=(0, 14))
        frm = tk.Frame(modal)
        frm.pack()
        # El usuario ya quedó configurado: se muestra fijo y solo se pide la contraseña.
        usuario_fijo = db.get_config("admin_user") or ""
        tk.Label(frm, text="Usuario:").grid(row=0, column=0, sticky="w", pady=6, padx=(0, 10))
        tk.Label(frm, text=usuario_fijo, font=("Segoe UI", 11, "bold")).grid(
            row=0, column=1, sticky="w", pady=6)
        tk.Label(frm, text="Contraseña:").grid(row=1, column=0, sticky="w", pady=6, padx=(0, 10))
        e_pass = tk.Entry(frm, width=22, show="*")
        e_pass.grid(row=1, column=1, pady=6)
        e_pass.focus()

        def intentar_login(event=None):
            if auth.verificar_login(usuario_fijo, e_pass.get()):
                self.usuario_actual = usuario_fijo
                modal.destroy()
                self.construir_dashboard()
                self.deiconify()
                self.after(400, self._recordar_clave_recuperacion)
                self.after(2000, self._sync_tick)
            else:
                messagebox.showerror("Error", "Contraseña incorrecta.", parent=modal)
                e_pass.delete(0, tk.END)

        e_pass.bind("<Return>", intentar_login)
        tk.Button(modal, text="Ingresar", command=intentar_login,
                  bg="#3B82F6", fg="white", activebackground="#3B82F6", activeforeground="white",
                  font=("Segoe UI", 11, "bold"), padx=40, pady=8).pack(pady=(16, 8))
        olvide = tk.Button(modal, text="¿Olvidaste tu contraseña?", bd=0, bg=PALETA["bg"],
                           fg="#7aa2ff", activebackground=PALETA["bg"], activeforeground="white",
                           font=("Segoe UI", 10, "underline"),
                           command=lambda: self._modal_olvide_password(modal))
        olvide.pack()

    def _modal_olvide_password(self, parent):
        p = PALETA
        modal = Ventana(parent)
        modal.configure(bg=p["bg"])
        modal.title("Recuperar contraseña")
        modal.geometry("460x470")
        modal.transient(parent)
        modal.grab_set()
        modal.resizable(False, False)

        tk.Label(modal, text="Recuperar contraseña", font=("Segoe UI", 15, "bold")).pack(pady=(20, 6))
        if not auth.tiene_clave_recuperacion():
            tk.Label(modal, wraplength=390, justify="left", fg=p["fg_muted"],
                     text="Esta instalación no tiene clave de recuperación (se crea al configurar "
                          "el sistema o la primera vez que entrás con esta versión).\n\n"
                          "Sin ella no se puede cambiar la contraseña sin perder los datos. Si "
                          "tenés un respaldo exportado (.json), podés instalar de cero y usar "
                          "'Importar respaldo'.").pack(padx=30, pady=14)
            tk.Button(modal, text="Entendido", command=modal.destroy, bg=p["bg_alt"], fg=p["fg"],
                      padx=24, pady=8).pack(pady=10)
            return

        tk.Label(modal, text="Ingresá la clave de recuperación que guardaste.",
                 fg=p["fg_muted"]).pack(pady=(0, 10))
        frm = tk.Frame(modal, padx=30)
        frm.pack(fill="x")
        tk.Label(frm, text="Clave de recuperación:").pack(anchor="w")
        e_clave = tk.Entry(frm, font=("Consolas", 12))
        e_clave.pack(fill="x", pady=(2, 10))
        tk.Label(frm, text="Nueva contraseña:").pack(anchor="w")
        e_nueva = tk.Entry(frm, show="*")
        e_nueva.pack(fill="x", pady=(2, 10))
        tk.Label(frm, text="Repetir nueva contraseña:").pack(anchor="w")
        e_rep = tk.Entry(frm, show="*")
        e_rep.pack(fill="x", pady=(2, 14))
        e_clave.focus()

        def restablecer():
            seg = auth.segundos_bloqueado()
            if seg > 0:
                messagebox.showerror("Bloqueado", f"Demasiados intentos. Esperá {seg} segundos.", parent=modal)
                return
            if len(e_nueva.get()) < 4:
                messagebox.showerror("Error", "La nueva contraseña es muy corta (mínimo 4).", parent=modal)
                return
            if e_nueva.get() != e_rep.get():
                messagebox.showerror("Error", "Las contraseñas no coinciden.", parent=modal)
                return
            nueva_clave = auth.restablecer_con_clave(e_clave.get(), e_nueva.get())
            if nueva_clave is None:
                extra = ""
                if auth.segundos_bloqueado() > 0:
                    extra = "\n\nSe bloqueó por 60 segundos por exceso de intentos."
                messagebox.showerror("Error", "La clave de recuperación no es correcta." + extra, parent=modal)
                return
            modal.destroy()
            messagebox.showinfo("Listo", "Contraseña cambiada. Ahora te mostramos tu NUEVA clave de "
                                         "recuperación: la anterior ya no sirve.", parent=parent)
            self._mostrar_clave_recuperacion(nueva_clave, parent=parent)

        tk.Button(modal, text="Cambiar contraseña", command=restablecer, bg="#3B82F6", fg="white",
                  activebackground="#3B82F6", activeforeground="white",
                  font=("Segoe UI", 11, "bold"), pady=8).pack(fill="x", padx=30)

    # ---------------- DASHBOARD ----------------
    def construir_dashboard(self):
        for w in self.winfo_children():
            w.destroy()
        p = PALETA
        self.configure(bg=p["bg"])

        # ---- barra lateral ----
        side = tk.Frame(self, bg=p["side"], width=215)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(side, bg=p["line"], width=1).pack(side="right", fill="y")
        tk.Button(side, text="Salir del sistema", command=self.salir_sistema, bg="#B42318",
                  fg="white", activebackground="#D92D20", activeforeground="white",
                  font=("Segoe UI", 10, "bold"), pady=7).pack(side="bottom", fill="x", padx=18, pady=14)
        if self.img_logo_front:
            tk.Label(side, image=self.img_logo_front, bg=p["side"]).pack(pady=(10, 0))
        elif self.img_logo_header:
            tk.Label(side, image=self.img_logo_header, bg=p["side"]).pack(pady=(20, 6))
        tk.Label(side, text="Balance personal", font=("Segoe UI", 14, "bold"),
                 bg=p["side"], fg="white").pack()
        tk.Label(side, text=f"Usuario: {self.usuario_actual}", font=("Segoe UI", 9),
                 bg=p["side"], fg=p["fg_muted"]).pack(pady=(1, 4))

        def seccion(texto):
            tk.Label(side, text=texto, font=("Segoe UI", 8, "bold"), bg=p["side"],
                     fg="#5d6585", anchor="w").pack(fill="x", padx=20, pady=(12, 3))

        def lateral(texto, cmd):
            fila = tk.Frame(side, bg=p["side"])
            fila.pack(fill="x")
            barra = tk.Frame(fila, bg=p["side"], width=3)
            barra.pack(side="left", fill="y")
            b = tk.Button(fila, text=texto, command=cmd, anchor="w", bg=p["side"], fg=p["fg"],
                          activebackground=p["side_hover"], activeforeground="white",
                          font=("Segoe UI", 10), padx=14, pady=5)
            b.pack(side="left", fill="x", expand=True)

            def entra(_):
                for w, c in ((fila, p["side_hover"]), (b, p["side_hover"]), (barra, p["select_bg"])):
                    w.config(bg=c)

            def sale(_):
                for w in (fila, b, barra):
                    w.config(bg=p["side"])
            b.bind("<Enter>", entra)
            b.bind("<Leave>", sale)

        seccion("GESTIÓN")
        lateral("Transferir entre cuentas", self.modal_transferencia)
        lateral("Cuentas por pagar", self.modal_cuentas_pagar)
        lateral("Gestionar cuentas", self.modal_gestionar_cuentas)
        lateral("Beneficiarios", self.modal_beneficiarios)
        lateral("Categorías", self.modal_categorias)
        seccion("ANÁLISIS")
        lateral("Reportes", self.modal_reportes)
        lateral("Análisis y gráficos", self.modal_analisis)
        lateral("Calculadora", self.modal_calculadora)
        seccion("DATOS Y SEGURIDAD")
        lateral("Sincronización en la nube", self.modal_nube)
        lateral("Exportar respaldo", self.exportar_datos)
        lateral("Importar respaldo", self.importar_datos)
        lateral("Contraseña y recuperación", self.modal_cambiar_password)

        # ---- zona principal ----
        main = tk.Frame(self, bg=p["bg"])
        main.pack(side="left", fill="both", expand=True, padx=20, pady=14)
        top = tk.Frame(main, bg=p["bg"])
        top.pack(fill="x")
        tk.Label(top, text="Resumen financiero", font=("Segoe UI", 18, "bold"),
                 bg=p["bg"], fg="white", anchor="w").pack(side="left")
        tk.Label(top, text=fecha_larga(), font=("Segoe UI", 10), bg=p["bg"],
                 fg=p["fg_muted"]).pack(side="right", pady=(8, 0))

        fila = tk.Frame(main, bg=p["bg"])
        fila.pack(fill="x", pady=(12, 0))
        for i in range(4):
            fila.grid_columnconfigure(i, weight=1, uniform="card")
        self.card_total = self._tarjeta(fila, 0, "DISPONIBLE TOTAL", "#4F8CFF")
        self.card_deudas = self._tarjeta(fila, 1, "DEUDAS PENDIENTES", "#F59E0B")
        self.card_neto = self._tarjeta(fila, 2, "NETO (DISPONIBLE − DEUDAS)", "#2FA36B")
        self.card_prom = self._tarjeta(fila, 3, "GASTO PROMEDIO POR DÍA", "#E5484D")
        self.fr_cuentas = tk.Frame(main, bg=p["bg"])
        self.fr_cuentas.pack(fill="x", pady=(10, 0))

        barra = tk.Frame(main, bg=p["bg"])
        barra.pack(fill="x", pady=(14, 8))
        tk.Label(barra, text="Movimientos", font=("Segoe UI", 13, "bold"),
                 bg=p["bg"], fg="white").pack(side="left")
        self.lbl_cant = tk.Label(barra, text="", font=("Segoe UI", 9), bg=p["bg"], fg=p["fg_muted"])
        self.lbl_cant.pack(side="left", padx=(10, 0), pady=(4, 0))

        def accion(txt, cmd, color):
            b = tk.Button(barra, text=txt, command=cmd, bg=color, fg="white", activebackground=color,
                          activeforeground="white", font=("Segoe UI", 10, "bold"), padx=14, pady=5)
            b.pack(side="right", padx=(6, 0))
            hov = mezclar(color, "#ffffff", 0.14)
            b.bind("<Enter>", lambda e: b.config(bg=hov))
            b.bind("<Leave>", lambda e: b.config(bg=color))
        accion("Eliminar", self.eliminar_seleccionado, "#475569")
        accion("Editar", self.editar_seleccionado, "#4F6BED")
        accion("−  Gasto", self.modal_nuevo_gasto, "#E5484D")
        accion("+  Ingreso", self.modal_nuevo_ingreso, "#2FA36B")
        accion("⇄  Transferir", self.modal_transferencia, "#7C5CFC")

        tabla_frame = tk.Frame(main, bg=p["bg"], highlightbackground=p["line"], highlightthickness=1)
        tabla_frame.pack(fill="both", expand=True)
        cols = ("fecha", "tipo", "categoria", "descripcion", "origen_destino",
                "forma_pago", "cuenta", "monto")
        self.tree = ttk.Treeview(tabla_frame, columns=cols, show="headings")
        encabezados = {"fecha": "Fecha", "tipo": "Tipo", "categoria": "Categoría",
                       "descripcion": "Descripción", "origen_destino": "Beneficiario",
                       "forma_pago": "Forma de pago", "cuenta": "Cuenta", "monto": "Monto"}
        anchos = {"fecha": 92, "tipo": 62, "categoria": 160, "descripcion": 140,
                  "origen_destino": 125, "forma_pago": 118, "cuenta": 105, "monto": 100}
        fijas = ("fecha", "tipo", "monto")
        for c in cols:
            self.tree.heading(c, text=encabezados[c], anchor="e" if c == "monto" else "w")
            self.tree.column(c, width=anchos[c], minwidth=50, stretch=(c not in fijas),
                             anchor="e" if c == "monto" else "w")
        self.tree.tag_configure("ingreso_par", foreground="#6fd69b", background="#15251d")
        self.tree.tag_configure("ingreso_impar", foreground="#6fd69b", background="#1a2d23")
        self.tree.tag_configure("gasto_par", foreground="#ff8f8f", background="#2a1a1f")
        self.tree.tag_configure("gasto_impar", foreground="#ff8f8f", background="#321f25")
        self.tree.tag_configure("transf_par", foreground="#9db8ff", background="#171e38")
        self.tree.tag_configure("transf_impar", foreground="#9db8ff", background="#1c2544")
        self.tree.pack(fill="both", expand=True, side="left")
        self.tree.bind("<Double-1>", lambda e: self.editar_seleccionado())
        scroll = ttk.Scrollbar(tabla_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscroll=scroll.set)

        self.actualizar_tabla()
        self.actualizar_saldo()

    def _tarjeta(self, parent, col, titulo, color):
        p = PALETA
        card = tk.Frame(parent, bg=p["card"], highlightbackground=p["line"], highlightthickness=1)
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
        tk.Frame(card, bg=color, height=3).pack(fill="x")
        cuerpo = tk.Frame(card, bg=p["card"], padx=14, pady=9)
        cuerpo.pack(fill="both", expand=True)
        tk.Label(cuerpo, text=titulo, font=("Segoe UI", 8, "bold"), bg=p["card"],
                 fg=p["fg_muted"], anchor="w").pack(fill="x")
        valor = tk.Label(cuerpo, text="", font=("Segoe UI", 17, "bold"), bg=p["card"],
                         fg="white", anchor="w")
        valor.pack(fill="x", pady=(4, 0))
        sub = tk.Label(cuerpo, text="", font=("Segoe UI", 9), bg=p["card"],
                       fg=p["fg_muted"], anchor="w")
        sub.pack(fill="x")
        return valor, sub

    # ---------- sincronización automática PC <-> celular ----------
    def _sync_iniciar(self, callback=None):
        if self._sync_activo or not sync.configurado():
            return False
        self._sync_activo = True
        self._sync_res = None

        def trabajo():
            try:
                res = sync.sincronizar_una_vez()
            except Exception as e:  # nunca debe romper la app
                res = {"subidos": 0, "aplicados": 0, "error": str(e)}
            self._sync_res = (res, callback)

        threading.Thread(target=trabajo, daemon=True).start()
        self.after(300, self._sync_esperar)
        return True

    def _sync_esperar(self):
        if self._sync_res is None:
            self.after(300, self._sync_esperar)
            return
        res, cb = self._sync_res
        self._sync_res = None
        self._sync_activo = False
        hora = time.strftime("%H:%M")
        self.title("Balance personal  ☁ " + (f"sin conexión ({hora})" if res.get("error") else f"sincronizado {hora}"))
        if res.get("aplicados"):
            try:
                self.actualizar_tabla()
                self.actualizar_saldo()
            except Exception:
                pass
        if cb:
            cb(res)

    def _sync_tick(self):
        if self._sync_loop:
            return
        self._sync_loop = True

        def ciclo():
            if self.usuario_actual and sync.configurado():
                self._sync_iniciar()
            self.after(20000, ciclo)

        ciclo()

    def modal_nube(self):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Sincronización en la nube")
        modal.geometry("560x640")
        modal.transient(self)
        modal.grab_set()
        modal.resizable(False, False)
        frm = tk.Frame(modal, padx=22, pady=16)
        frm.pack(fill="both", expand=True)

        def limpiar():
            for w in frm.winfo_children():
                w.destroy()

        def copiar(texto, aviso):
            self.clipboard_clear()
            self.clipboard_append(texto)
            messagebox.showinfo("Copiado", aviso, parent=modal)

        def pantalla():
            limpiar()
            if sync.configurado():
                d = sync.datos_conexion()
                tk.Label(frm, text="☁  Conectado", font=("Segoe UI", 14, "bold")).pack(anchor="w")
                tk.Label(frm, text=f"Cuenta: {d['email']}\nÚltima sincronización: {sync.get_estado('nube_ultima', '—')}",
                         justify="left", fg=PALETA["fg_muted"]).pack(anchor="w", pady=(6, 12))
                tk.Label(frm, text="La PC y el celular se actualizan solos cada pocos segundos mientras "
                                   "están abiertos y con internet. Lo que cargues en uno aparece en el otro.",
                         wraplength=500, justify="left").pack(anchor="w", pady=(0, 14))
                estado = tk.Label(frm, text="", fg=PALETA["fg_muted"])

                def ahora():
                    estado.config(text="Sincronizando…")
                    if not self._sync_iniciar(lambda r: (estado.winfo_exists() and estado.config(
                            text=("Error: " + r["error"]) if r.get("error") else
                            f"Listo. Subidos: {r['subidos']}  Bajados: {r['aplicados']}"))):
                        estado.config(text="Ya hay una sincronización en curso.")

                tk.Button(frm, text="Sincronizar ahora", command=ahora, bg="#2FA36B", fg="white", pady=8).pack(fill="x")
                estado.pack(anchor="w", pady=6)
                tk.Button(frm, text="Copiar código para conectar el celular",
                          command=lambda: copiar(sync.codigo_para_celular(),
                                                 "Código copiado. Envialo al celular (por ejemplo por WhatsApp) y pegalo "
                                                 "en la app: Más > Respaldo y seguridad > Nube.\nNo incluye tu contraseña."),
                          bg=PALETA["card"], fg="white", pady=8).pack(fill="x", pady=(10, 0))

                def desconectar():
                    if messagebox.askyesno("Desconectar", "Este equipo dejará de sincronizar. Los datos locales "
                                           "se conservan. ¿Desconectar?", parent=modal):
                        sync.desconectar()
                        pantalla()

                tk.Button(frm, text="Desconectar este equipo", command=desconectar, bg="#475569", fg="white",
                          pady=8).pack(fill="x", pady=(10, 0))
                return
            tk.Label(frm, text="Conectar a la nube", font=("Segoe UI", 14, "bold")).pack(anchor="w")
            tk.Label(frm, text="Para que la PC y el celular se mantengan iguales sin exportar ni importar. "
                               "Necesitás un proyecto gratuito en supabase.com (te lo explico en el archivo LEEME_NUBE.txt). "
                               "Los datos viajan por internet con HTTPS y solo vos podés verlos.",
                     wraplength=510, justify="left", fg=PALETA["fg_muted"]).pack(anchor="w", pady=(4, 10))
            campos = {}
            for clave, rotulo, oculto in (("url", "URL del proyecto (https://xxxx.supabase.co):", False),
                                          ("key", "Clave pública (anon public key):", False),
                                          ("email", "Tu correo (identifica tu cuenta en la nube):", False),
                                          ("pass", "Contraseña de la nube (distinta a la de la app):", True)):
                tk.Label(frm, text=rotulo).pack(anchor="w")
                e = tk.Entry(frm, show="*" if oculto else "")
                e.pack(fill="x", pady=(0, 8))
                campos[clave] = e
            d = sync.datos_conexion()
            for k in ("url", "key", "email"):
                if d[k]:
                    campos[k].insert(0, d[k])
            var_crear = tk.BooleanVar(value=False)
            tk.Checkbutton(frm, text="Es la primera vez: crear mi cuenta en la nube", variable=var_crear,
                           selectcolor=PALETA["card"]).pack(anchor="w")
            tk.Button(frm, text="Copiar script SQL para Supabase", bg=PALETA["card"], fg="white",
                      command=lambda: copiar(sync.SQL_SUPABASE, "Script copiado. En Supabase: SQL Editor > New query > "
                                             "pegar > Run (se hace una sola vez).")).pack(anchor="w", pady=(8, 0))

            def conectar():
                url, key = campos["url"].get().strip(), campos["key"].get().strip()
                email, pw = campos["email"].get().strip(), campos["pass"].get()
                if not (url and key and email and pw):
                    messagebox.showerror("Error", "Completá los cuatro campos.", parent=modal)
                    return
                try:
                    modal.config(cursor="watch")
                    modal.update_idletasks()
                    sync.iniciar_sesion(url, key, email, pw, crear=var_crear.get())
                    if sync.hay_datos_en_nube():
                        tiene = bool(db.get_movimientos(incluir_transferencias=True) or db.get_cuentas())
                        if tiene and not messagebox.askyesno(
                                "La nube ya tiene datos",
                                "En la nube ya hay datos guardados.\n\nPara quedar iguales, los datos de ESTE equipo "
                                "se reemplazarán por los de la nube.\n\n¿Continuar?", parent=modal):
                            sync.desconectar()
                            return
                        sync.reemplazar_local_con_nube()
                except sync.ErrorNube as e:
                    messagebox.showerror("No se pudo conectar", str(e), parent=modal)
                    return
                finally:
                    modal.config(cursor="")
                self._sync_iniciar(lambda r: None)
                self.actualizar_tabla()
                self.actualizar_saldo()
                pantalla()

            tk.Button(frm, text="Conectar", command=conectar, bg="#2FA36B", fg="white", pady=9).pack(fill="x", pady=(14, 0))

        pantalla()

    def actualizar_saldo(self):
        p = PALETA
        cuentas = db.get_saldos_cuentas()
        total = sum(c["saldo_actual"] for c in cuentas)
        pendiente = db.get_total_pendiente()
        neto = total - pendiente
        st = db.get_stats_gasto_diario()
        self.card_total[0].config(text=dinero(total))
        self.card_total[1].config(text=f"{len(cuentas)} cuenta(s)")
        self.card_deudas[0].config(text=dinero(pendiente), fg="#F59E0B" if pendiente > 0 else "white")
        self.card_deudas[1].config(text="Sin deudas pendientes" if pendiente <= 0 else "Por pagar")
        self.card_neto[0].config(text=dinero(neto), fg="#6fd69b" if neto >= 0 else "#ff8f8f")
        self.card_neto[1].config(text="Lo que realmente te queda")
        self.card_prom[0].config(text=dinero(st['promedio']))
        self.card_prom[1].config(text=f"Últimos 7 días: {dinero(st['prom7'])}\nHoy: {dinero(st['hoy'])}", justify="left")
        for w in self.fr_cuentas.winfo_children():
            w.destroy()
        for c in cuentas:
            chip = tk.Frame(self.fr_cuentas, bg=p["card"], padx=12, pady=5,
                            highlightbackground=p["line"], highlightthickness=1)
            chip.pack(side="left", padx=(0, 8))
            tk.Label(chip, text=c["nombre"], font=("Segoe UI", 9), bg=p["card"],
                     fg=p["fg_muted"]).pack(side="left")
            tk.Label(chip, text="  " + dinero(c["saldo_actual"]), font=("Segoe UI", 10, "bold"),
                     bg=p["card"], fg="white" if c["saldo_actual"] >= 0 else "#ff8f8f").pack(side="left")

    def actualizar_tabla(self, filas=None):
        for i in self.tree.get_children():
            self.tree.delete(i)
        filas = filas if filas is not None else db.get_movimientos(incluir_transferencias=True)
        if hasattr(self, "lbl_cant"):
            self.lbl_cant.config(text=f"{len(filas)} registros")
        for idx, f in enumerate(filas):
            paridad = "par" if idx % 2 == 0 else "impar"
            es_transf = f["transferencia_id"] is not None
            self.tree.insert("", "end", iid=str(f["id"]), values=(
                iso_a_disp(f["fecha"]), "Transf." if es_transf else f["tipo"].capitalize(), f["categoria"],
                f["descripcion"] or "", f["origen_destino"] or "",
                f["forma_pago"] or "-", f["cuenta"] or "-",
                f"${f['monto']:,.2f}",
            ), tags=(f"{'transf' if es_transf else f['tipo']}_{paridad}",))

    def eliminar_seleccionado(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Atención", "Seleccioná primero una fila de la tabla.")
            return
        mov = db.get_movimiento(int(sel[0]))
        if mov is not None and mov["transferencia_id"] is not None:
            texto = ("¿Eliminar esta transferencia?\nSe borran las dos partes "
                     "(la salida y la entrada) y los saldos vuelven a como estaban.")
        else:
            texto = "¿Eliminar el movimiento seleccionado?"
        if messagebox.askyesno("Confirmar", texto):
            db.delete_movimiento(int(sel[0]))
            self.actualizar_tabla()
            self.actualizar_saldo()

    def editar_seleccionado(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Atención", "Seleccioná primero una fila de la tabla para editar.")
            return
        mov = db.get_movimiento(int(sel[0]))
        if mov is None:
            messagebox.showerror("Error", "Ese movimiento ya no existe.")
            return
        if mov["transferencia_id"] is not None:
            messagebox.showinfo("Transferencia", "Las transferencias no se editan.\n"
                                "Eliminala (botón Eliminar) y creala de nuevo con los datos correctos.")
            return
        self._modal_movimiento(mov["tipo"], movimiento_existente=mov)

    def salir_sistema(self):
        if messagebox.askyesno("Salir", "¿Seguro que querés cerrar el sistema?"):
            self.destroy()

    # ---------------- MODAL: NUEVO / EDITAR MOVIMIENTO ----------------
    def _modal_movimiento(self, tipo, movimiento_existente=None):
        es_edicion = movimiento_existente is not None
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        if es_edicion:
            titulo = f"Editar {'ingreso' if tipo == 'ingreso' else 'gasto'}"
        else:
            titulo = "Nuevo ingreso" if tipo == "ingreso" else "Nuevo gasto"
        modal.title(titulo)
        modal.geometry("460x590")
        modal.transient(self)
        modal.grab_set()
        modal.resizable(False, False)

        categorias_fijas = CATEGORIAS_INGRESO if tipo == "ingreso" else CATEGORIAS_GASTO
        categorias = list(categorias_fijas)
        for c in db.get_categorias_usadas(tipo):
            if c not in categorias:
                categorias.append(c)
        categorias.sort(key=db.clave_orden)  # orden alfabético

        cuentas_disponibles = db.get_nombres_cuentas()

        frm = tk.Frame(modal, padx=20, pady=15)
        frm.pack(fill="both", expand=True)

        tk.Label(frm, text="Fecha:").pack(anchor="w")
        fecha_inicial = movimiento_existente["fecha"] if es_edicion else datetime.now().strftime("%Y-%m-%d")
        sel_fecha = SelectorFecha(frm, fecha_inicial_iso=fecha_inicial)
        sel_fecha.pack(anchor="w", pady=(0, 10))

        label_origen = ("¿De dónde proviene? (ej: cooperativa, jornada)"
                         if tipo == "ingreso" else
                         "¿A quién se pagó / dónde se compró?  (se recuerda)")
        tk.Label(frm, text=label_origen).pack(anchor="w")
        nombres_benef = [b["nombre"] for b in db.get_beneficiarios()]
        cb_origen = ttk.Combobox(frm, values=nombres_benef)  # editable: escribís y filtra
        cb_origen.pack(fill="x", pady=(0, 10))
        if es_edicion:
            cb_origen.set(movimiento_existente["origen_destino"] or "")
        auto = {"ultimo": cb_origen.get().strip().lower()}

        def filtrar_benef(event):
            if event.keysym in ("Up", "Down", "Return", "Escape", "Tab", "Left", "Right",
                                "Shift_L", "Shift_R"):
                return
            t = db.clave_orden(cb_origen.get())
            cb_origen["values"] = [n for n in nombres_benef if t in db.clave_orden(n)] if t else nombres_benef

        def autocompletar(event=None):
            clave = cb_origen.get().strip().lower()
            if es_edicion or not clave or clave == auto["ultimo"]:
                return
            b = db.get_beneficiario(clave)
            if b is None:
                return
            auto["ultimo"] = clave
            if b["tipo"] == tipo and b["categoria"]:
                cb_cat.set(b["categoria"])
            if b["forma_pago"] in FORMAS_PAGO:
                cb_forma.set(b["forma_pago"])
            if b["cuenta"] in cuentas_disponibles:
                cb_cuenta.set(b["cuenta"])

        cb_origen.bind("<KeyRelease>", filtrar_benef)
        cb_origen.bind("<<ComboboxSelected>>", autocompletar)
        cb_origen.bind("<FocusOut>", autocompletar)


        NUEVA_CAT = "➕  Nueva categoría…"
        if es_edicion and movimiento_existente["categoria"] not in categorias:
            categorias.append(movimiento_existente["categoria"])
            categorias.sort(key=db.clave_orden)
        tk.Label(frm, text="Categoría:").pack(anchor="w")
        cb_cat = ttk.Combobox(frm, values=categorias + [NUEVA_CAT], state="readonly")
        cb_cat.pack(fill="x", pady=(0, 10))
        if es_edicion:
            cb_cat.set(movimiento_existente["categoria"])
        else:
            cb_cat.set(categorias_fijas[0])
        prev_cat = {"v": cb_cat.get()}

        def al_elegir_cat(event=None):
            if cb_cat.get() == NUEVA_CAT:
                n = simpledialog.askstring("Nueva categoría", "Nombre de la categoría:", parent=modal)
                n = " ".join((n or "").split())
                if n:
                    if n not in categorias:
                        categorias.append(n)
                        categorias.sort(key=db.clave_orden)
                        cb_cat["values"] = categorias + [NUEVA_CAT]
                    cb_cat.set(n)
                else:
                    cb_cat.set(prev_cat["v"])
            prev_cat["v"] = cb_cat.get()

        cb_cat.bind("<<ComboboxSelected>>", al_elegir_cat)

        tk.Label(frm, text="Descripción (detalle: qué se compró o pagó):").pack(anchor="w")
        descripciones = db.get_descripciones_usadas()
        e_desc = ttk.Combobox(frm, values=descripciones)  # editable: escribís y filtra
        e_desc.pack(fill="x", pady=(0, 10))

        def filtrar_desc(event):
            if event.keysym in ("Up", "Down", "Return", "Escape", "Tab", "Left", "Right",
                                "Shift_L", "Shift_R"):
                return
            t = db.clave_orden(e_desc.get())
            e_desc["values"] = [d for d in descripciones if t in db.clave_orden(d)] if t else descripciones

        e_desc.bind("<KeyRelease>", filtrar_desc)
        if es_edicion:
            e_desc.insert(0, movimiento_existente["descripcion"] or "")

        tk.Label(frm, text="Forma de pago:").pack(anchor="w")
        cb_forma = ttk.Combobox(frm, values=FORMAS_PAGO, state="readonly")
        if es_edicion and movimiento_existente["forma_pago"] in FORMAS_PAGO:
            cb_forma.set(movimiento_existente["forma_pago"])
        else:
            cb_forma.current(0)
        cb_forma.pack(fill="x", pady=(0, 10))

        label_cuenta = ("¿A qué cuenta ingresa el dinero?"
                         if tipo == "ingreso" else
                         "¿De qué cuenta se descuenta?")
        tk.Label(frm, text=label_cuenta).pack(anchor="w")
        if cuentas_disponibles:
            cb_cuenta = ttk.Combobox(frm, values=cuentas_disponibles, state="readonly")
            if es_edicion and movimiento_existente["cuenta"] in cuentas_disponibles:
                cb_cuenta.set(movimiento_existente["cuenta"])
            else:
                cb_cuenta.current(0)
        else:
            # No debería pasar (el setup crea 3 cuentas), pero por las dudas
            # no se bloquea el registro del movimiento.
            cb_cuenta = ttk.Combobox(frm, values=[])
            messagebox.showwarning(
                "Atención",
                "No hay ninguna cuenta configurada. Creá una desde "
                "'Gestionar cuentas' para poder descontar el gasto de algún lado.",
                parent=modal,
            )
        cb_cuenta.pack(fill="x", pady=(0, 10))

        tk.Label(frm, text="Monto ($):").pack(anchor="w")
        e_monto = tk.Entry(frm)
        e_monto.pack(fill="x", pady=(0, 15))
        if es_edicion:
            e_monto.insert(0, f"{movimiento_existente['monto']:g}")

        def guardar():
            try:
                monto = float(e_monto.get().replace(",", "."))
                if monto <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Ingresá un monto válido mayor a cero.", parent=modal)
                return
            fecha_disp = sel_fecha.get_disp()
            if not fecha_disp:
                messagebox.showerror("Error", "Elegí una fecha con el botón 📅.", parent=modal)
                return
            try:
                fecha_iso = disp_a_iso(fecha_disp)
            except ValueError:
                messagebox.showerror("Error", "La fecha no es válida.", parent=modal)
                return
            categoria = cb_cat.get().strip()
            if not categoria:
                messagebox.showerror("Error", "La categoría no puede quedar vacía.", parent=modal)
                return
            cuenta = cb_cuenta.get().strip()
            if not cuenta:
                messagebox.showerror("Error", "Elegí de qué cuenta sale (o a qué cuenta entra) el dinero.",
                                      parent=modal)
                return
            if es_edicion:
                db.update_movimiento(movimiento_existente["id"], fecha_iso, categoria,
                                      e_desc.get().strip(), cb_origen.get().strip(), monto,
                                      cb_forma.get(), cuenta)
            else:
                db.add_movimiento(fecha_iso, tipo, categoria, e_desc.get().strip(),
                                   cb_origen.get().strip(), monto, cb_forma.get(), cuenta)
            self.actualizar_tabla()
            self.actualizar_saldo()
            modal.destroy()

        texto_boton = "Guardar cambios" if es_edicion else "Guardar"
        tk.Button(frm, text=texto_boton, command=guardar,
                  bg="#2FA36B" if tipo == "ingreso" else "#E5484D",
                  fg="white", pady=8).pack(fill="x")

    def modal_nuevo_ingreso(self):
        self._modal_movimiento("ingreso")

    def modal_nuevo_gasto(self):
        self._modal_movimiento("gasto")

    def modal_transferencia(self):
        cuentas = db.get_nombres_cuentas()
        if len(cuentas) < 2:
            messagebox.showinfo("Transferencia", "Necesitás al menos 2 cuentas para transferir.\n"
                                "Creá otra desde 'Gestionar cuentas'.")
            return
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Transferencia entre cuentas")
        modal.geometry("460x520")
        modal.transient(self)
        modal.grab_set()
        modal.resizable(False, False)
        frm = tk.Frame(modal, padx=20, pady=15)
        frm.pack(fill="both", expand=True)
        tk.Label(frm, text="Mueve dinero de una cuenta a otra. No cuenta como ingreso ni gasto.",
                 font=("Segoe UI", 9), fg=PALETA["fg_muted"], wraplength=400, justify="left").pack(anchor="w", pady=(0, 10))
        tk.Label(frm, text="Fecha:").pack(anchor="w")
        sel_fecha = SelectorFecha(frm, fecha_inicial_iso=datetime.now().strftime("%Y-%m-%d"))
        sel_fecha.pack(anchor="w", pady=(0, 10))
        tk.Label(frm, text="Cuenta de origen (de dónde sale el dinero):").pack(anchor="w")
        cb_o = ttk.Combobox(frm, values=cuentas, state="readonly")
        cb_o.current(0)
        cb_o.pack(fill="x", pady=(0, 10))
        tk.Label(frm, text="Cuenta de destino (a dónde entra):").pack(anchor="w")
        cb_d = ttk.Combobox(frm, values=cuentas, state="readonly")
        cb_d.current(1)
        cb_d.pack(fill="x", pady=(0, 10))
        tk.Label(frm, text="Monto ($):").pack(anchor="w")
        e_monto = tk.Entry(frm)
        e_monto.pack(fill="x", pady=(0, 10))
        tk.Label(frm, text="Detalle (opcional):").pack(anchor="w")
        e_desc = tk.Entry(frm)
        e_desc.pack(fill="x", pady=(0, 15))

        def guardar():
            try:
                monto = float(e_monto.get().replace(",", "."))
                if monto <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Ingresá un monto válido mayor a cero.", parent=modal)
                return
            fecha_disp = sel_fecha.get_disp()
            if not fecha_disp:
                messagebox.showerror("Error", "Elegí una fecha con el botón 📅.", parent=modal)
                return
            try:
                fecha_iso = disp_a_iso(fecha_disp)
                db.add_transferencia(fecha_iso, cb_o.get(), cb_d.get(), monto, e_desc.get().strip())
            except ValueError as e:
                messagebox.showerror("Error", str(e) or "Datos inválidos.", parent=modal)
                return
            self.actualizar_tabla()
            self.actualizar_saldo()
            modal.destroy()

        tk.Button(frm, text="Transferir", command=guardar, bg="#7C5CFC", fg="white", pady=8).pack(fill="x")

    # ---------------- MODAL: REPORTES ----------------
    def modal_reportes(self):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Reportes")
        modal.geometry("480x540")
        modal.transient(self)
        modal.grab_set()
        modal.resizable(False, False)

        frm = tk.Frame(modal, padx=20, pady=15)
        frm.pack(fill="both", expand=True)

        tk.Label(frm, text="Desde (opcional):").pack(anchor="w")
        sel_desde = SelectorFecha(frm)
        sel_desde.pack(anchor="w", pady=(0, 8))

        tk.Label(frm, text="Hasta (opcional):").pack(anchor="w")
        sel_hasta = SelectorFecha(frm)
        sel_hasta.pack(anchor="w", pady=(0, 8))

        tk.Label(frm, text="Tipo:").pack(anchor="w")
        cb_tipo = ttk.Combobox(frm, values=["Todos", "Ingreso", "Gasto"], state="readonly")
        cb_tipo.current(0)
        cb_tipo.pack(fill="x", pady=(0, 8))

        todas_cats = ["Todas"] + sorted(set(CATEGORIAS_INGRESO + CATEGORIAS_GASTO
                                           + db.get_categorias_usadas("ingreso") + db.get_categorias_usadas("gasto")),
                                       key=db.clave_orden)
        tk.Label(frm, text="Categoría:").pack(anchor="w")
        cb_cat = ttk.Combobox(frm, values=todas_cats, state="readonly")
        cb_cat.current(0)
        cb_cat.pack(fill="x", pady=(0, 15))

        def _filtrar():
            tipo = None if cb_tipo.get() == "Todos" else cb_tipo.get().lower()
            categoria = None if cb_cat.get() == "Todas" else cb_cat.get()
            desde_disp = sel_desde.get_disp()
            hasta_disp = sel_hasta.get_disp()
            try:
                desde = disp_a_iso(desde_disp) if desde_disp else None
                hasta = disp_a_iso(hasta_disp) if hasta_disp else None
            except ValueError:
                messagebox.showerror("Error", "Las fechas deben elegirse con el calendario.", parent=modal)
                return None
            return db.get_movimientos(desde, hasta, tipo, categoria)

        def aplicar():
            filas = _filtrar()
            if filas is None:
                return
            modal.destroy()
            self.mostrar_reporte_tickets(filas)

        def exportar_csv():
            filas = _filtrar()
            if filas is None:
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                initialfile="reporte.csv",
            )
            if not path:
                return
            db.export_csv(path, filas)
            messagebox.showinfo("Listo", f"Reporte exportado a:\n{path}", parent=modal)

        tk.Button(frm, text="Ver reporte", command=aplicar,
                  bg="#3B82F6", fg="white", pady=6).pack(fill="x", pady=(0, 6))
        tk.Button(frm, text="Exportar a CSV", command=exportar_csv,
                  bg="#0E9F8E", fg="white", pady=6).pack(fill="x")

    def mostrar_reporte_tickets(self, filas):
        """Muestra el resultado de un reporte como una lista de 'tickets'
        (uno por movimiento), con colores alternados para leerlos fácil,
        en vez de una tabla apretada."""
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Resultado del reporte")
        modal.geometry("740x680")
        modal.transient(self)
        modal.grab_set()

        total_ingresos = sum(f["monto"] for f in filas if f["tipo"] == "ingreso")
        total_gastos = sum(f["monto"] for f in filas if f["tipo"] == "gasto")
        neto = total_ingresos - total_gastos

        resumen = tk.Frame(modal, bg=PALETA["bg_alt"], pady=10)
        resumen.pack(fill="x")
        tk.Label(resumen, text=f"{len(filas)} movimientos", font=("Segoe UI", 13, "bold"),
                 bg=PALETA["bg_alt"], fg=PALETA["fg"]).pack(anchor="w", padx=15)
        tk.Label(resumen,
                 text=f"Ingresos: ${total_ingresos:,.2f}   |   Gastos: ${total_gastos:,.2f}   |   "
                      f"Neto: ${neto:,.2f}",
                 font=("Segoe UI", 11, "bold"), bg=PALETA["bg_alt"],
                 fg="#7cd992" if neto >= 0 else "#ff8a80").pack(anchor="w", padx=15, pady=(2, 0))

        if not filas:
            tk.Label(modal, text="No se encontró ningún movimiento con esos filtros.",
                     bg=PALETA["bg"], fg=PALETA["fg_muted"], font=("Segoe UI", 11),
                     pady=30).pack()
        else:
            contenedor = tk.Frame(modal, bg=PALETA["bg"])
            contenedor.pack(fill="both", expand=True)

            canvas = tk.Canvas(contenedor, bg=PALETA["bg"], highlightthickness=0)
            scroll = ttk.Scrollbar(contenedor, orient="vertical", command=canvas.yview)
            lista = tk.Frame(canvas, bg=PALETA["bg"])

            lista.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            ventana_id = canvas.create_window((0, 0), window=lista, anchor="nw")
            canvas.bind("<Configure>", lambda e: canvas.itemconfig(ventana_id, width=e.width))
            canvas.configure(yscrollcommand=scroll.set)
            canvas.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")

            def _rueda(event):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

            canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _rueda))
            canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
            modal.protocol("WM_DELETE_WINDOW", lambda: (canvas.unbind_all("<MouseWheel>"), modal.destroy()))

            for idx, f in enumerate(filas):
                es_ingreso = f["tipo"] == "ingreso"
                bg_ticket = "#1c2b20" if es_ingreso else "#2b1e1e"
                if idx % 2 == 1:
                    bg_ticket = "#213329" if es_ingreso else "#332222"
                color_monto = "#7cd992" if es_ingreso else "#ff8a80"
                signo = "+" if es_ingreso else "-"

                ticket = tk.Frame(lista, bg=bg_ticket)
                ticket.pack(fill="x", padx=10, pady=(0, 6))

                franja = tk.Frame(ticket, bg=color_monto, width=5)
                franja.pack(side="left", fill="y")

                cuerpo = tk.Frame(ticket, bg=bg_ticket, padx=12, pady=8)
                cuerpo.pack(side="left", fill="both", expand=True)

                fila_arriba = tk.Frame(cuerpo, bg=bg_ticket)
                fila_arriba.pack(fill="x")
                tk.Label(fila_arriba, text=iso_a_disp(f["fecha"]), bg=bg_ticket,
                         fg=PALETA["fg_muted"], font=("Segoe UI", 10)).pack(side="left")
                tk.Label(fila_arriba, text=f"{signo} ${f['monto']:,.2f}", bg=bg_ticket,
                         fg=color_monto, font=("Segoe UI", 14, "bold")).pack(side="right")

                tk.Label(cuerpo, text=f["categoria"], bg=bg_ticket, fg=PALETA["fg"],
                         font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", pady=(2, 0))
                if f["descripcion"]:
                    tk.Label(cuerpo, text=f["descripcion"], bg=bg_ticket, fg=PALETA["fg"],
                             font=("Segoe UI", 10), anchor="w", wraplength=480,
                             justify="left").pack(fill="x")

                detalle = " · ".join(filter(None, [
                    f["origen_destino"] or None,
                    f["forma_pago"] or None,
                    f["cuenta"] or None,
                ]))
                if detalle:
                    tk.Label(cuerpo, text=detalle, bg=bg_ticket, fg=PALETA["fg_muted"],
                             font=("Segoe UI", 10), anchor="w").pack(fill="x", pady=(2, 0))

        abajo = tk.Frame(modal, bg=PALETA["bg"], pady=8)
        abajo.pack(fill="x")
        tk.Button(abajo, text="Exportar a CSV", bg="#0E9F8E", fg="white", padx=10, pady=6,
                  command=lambda: self._exportar_csv_directo(filas)).pack(side="left", padx=15)
        tk.Button(abajo, text="Cerrar", bg="#475569", fg="white", padx=10, pady=6,
                  command=modal.destroy).pack(side="right", padx=15)

    def _exportar_csv_directo(self, filas):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile="reporte.csv",
        )
        if not path:
            return
        db.export_csv(path, filas)
        messagebox.showinfo("Listo", f"Reporte exportado a:\n{path}")

    # ---------------- MODAL: CUENTAS POR PAGAR ----------------
    def modal_cuentas_pagar(self):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Cuentas por pagar (préstamos, deudas, servicios)")
        modal.geometry("1000x540")
        modal.transient(self)
        modal.grab_set()

        top = tk.Frame(modal, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="Cuentas por pagar", font=("Segoe UI", 13, "bold")).pack(side="left", padx=10)
        lbl_total_pend = tk.Label(top, text="", font=("Segoe UI", 11, "bold"), fg="#ff8f8f")
        lbl_total_pend.pack(side="right", padx=10)

        tabla_frame = tk.Frame(modal)
        tabla_frame.pack(fill="both", expand=True, padx=10, pady=5)
        cols = ("tipo", "descripcion", "acreedor", "monto_total", "monto_pagado",
                "pendiente", "vencimiento", "estado")
        tree = ttk.Treeview(tabla_frame, columns=cols, show="headings")
        encab = {"tipo": "Tipo", "descripcion": "Descripción", "acreedor": "A quién / proveedor",
                  "monto_total": "Monto total", "monto_pagado": "Pagado", "pendiente": "Pendiente",
                  "vencimiento": "Vencimiento", "estado": "Estado"}
        anchos = {"tipo": 80, "descripcion": 190, "acreedor": 140, "monto_total": 95,
                  "monto_pagado": 90, "pendiente": 95, "vencimiento": 95, "estado": 80}
        for c in cols:
            tree.heading(c, text=encab[c])
            tree.column(c, width=anchos[c])
        tree.tag_configure("pagada", foreground="#9a9ab0")
        tree.tag_configure("pendiente", foreground="#ff8a80")
        tree.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(tabla_frame, orient="vertical", command=tree.yview)
        scroll.pack(side="right", fill="y")
        tree.configure(yscroll=scroll.set)

        def refrescar():
            for i in tree.get_children():
                tree.delete(i)
            filas = db.get_cuentas_pagar()
            total_pend = 0.0
            for f in filas:
                pend = f["monto_total"] - f["monto_pagado"]
                if f["estado"] == "pendiente":
                    total_pend += pend
                venc = iso_a_disp(f["fecha_vencimiento"]) if f["fecha_vencimiento"] else "-"
                tree.insert("", "end", iid=str(f["id"]), values=(
                    f["tipo"], f["descripcion"], f["acreedor"] or "",
                    f"${f['monto_total']:,.2f}", f"${f['monto_pagado']:,.2f}",
                    f"${pend:,.2f}", venc, f["estado"].capitalize(),
                ), tags=(f["estado"],))
            lbl_total_pend.config(text=f"Total pendiente: ${total_pend:,.2f}")

        botones = tk.Frame(modal, pady=8)
        botones.pack(fill="x")

        def nueva_deuda():
            self._modal_nueva_deuda(refrescar)

        def abonar():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Atención", "Seleccioná una cuenta de la tabla.", parent=modal)
                return
            self._modal_abonar_deuda(int(sel[0]), refrescar)

        def eliminar():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Atención", "Seleccioná una cuenta de la tabla.", parent=modal)
                return
            if messagebox.askyesno(
                "Confirmar",
                "¿Eliminar esta cuenta por pagar?\n\n"
                "Esto solo borra el registro de la deuda; no borra los movimientos "
                "de gasto que ya se generaron por abonos anteriores.",
                parent=modal,
            ):
                db.delete_cuenta_pagar(int(sel[0]))
                refrescar()

        tk.Button(botones, text="+ Nueva deuda", command=nueva_deuda,
                  bg="#2FA36B", fg="white", padx=8, pady=6).pack(side="left", padx=5)
        tk.Button(botones, text="Abonar / Pagar", command=abonar,
                  bg="#3B82F6", fg="white", padx=8, pady=6).pack(side="left", padx=5)
        tk.Button(botones, text="Eliminar", command=eliminar,
                  bg="#475569", fg="white", padx=8, pady=6).pack(side="left", padx=5)

        refrescar()

    def _modal_nueva_deuda(self, refrescar):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Nueva cuenta por pagar")
        modal.geometry("440x600")
        modal.transient(self)
        modal.grab_set()
        modal.resizable(False, False)
        frm = tk.Frame(modal, padx=20, pady=15)
        frm.pack(fill="both", expand=True)

        tk.Label(frm, text="Tipo:").pack(anchor="w")
        cb_tipo = ttk.Combobox(frm, values=CATEGORIAS_DEUDA, state="readonly")
        cb_tipo.current(0)
        cb_tipo.pack(fill="x", pady=(0, 10))

        tk.Label(frm, text="Descripción (ej: préstamo de Joseph, internet CANTV):").pack(anchor="w")
        e_desc = tk.Entry(frm)
        e_desc.pack(fill="x", pady=(0, 10))

        tk.Label(frm, text="A quién se le debe / proveedor:").pack(anchor="w")
        e_acreedor = ttk.Combobox(frm, values=[b["nombre"] for b in db.get_beneficiarios()])
        e_acreedor.pack(fill="x", pady=(0, 10))

        tk.Label(frm, text="Monto total de la deuda ($):").pack(anchor="w")
        e_monto = tk.Entry(frm)
        e_monto.pack(fill="x", pady=(0, 10))

        tk.Label(frm, text="Ya pagado hasta ahora ($, opcional):").pack(anchor="w")
        e_pagado = tk.Entry(frm)
        e_pagado.insert(0, "0")
        e_pagado.pack(fill="x", pady=(0, 10))

        tk.Label(frm, text="Fecha de vencimiento (opcional):").pack(anchor="w")
        sel_venc = SelectorFecha(frm)
        sel_venc.pack(anchor="w", pady=(0, 15))

        def guardar():
            try:
                monto = float(e_monto.get().replace(",", "."))
                pagado = float((e_pagado.get() or "0").replace(",", "."))
                if monto <= 0 or pagado < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Revisá los montos ingresados.", parent=modal)
                return
            if not e_desc.get().strip():
                messagebox.showerror("Error", "La descripción es obligatoria.", parent=modal)
                return
            venc_disp = sel_venc.get_disp()
            venc_iso = None
            if venc_disp:
                try:
                    venc_iso = disp_a_iso(venc_disp)
                except ValueError:
                    messagebox.showerror("Error", "La fecha de vencimiento no es válida.", parent=modal)
                    return
            db.add_cuenta_pagar(cb_tipo.get(), e_desc.get().strip(), e_acreedor.get().strip(),
                                 monto, pagado, venc_iso)
            refrescar()
            modal.destroy()

        tk.Button(frm, text="Guardar", command=guardar,
                  bg="#2FA36B", fg="white", pady=8).pack(fill="x")

    def _modal_abonar_deuda(self, id_, refrescar):
        cuenta = db.get_cuenta_pagar(id_)
        if not cuenta:
            return
        pendiente = cuenta["monto_total"] - cuenta["monto_pagado"]
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Abonar / pagar")
        modal.geometry("440x500")
        modal.transient(self)
        modal.grab_set()
        modal.resizable(False, False)
        frm = tk.Frame(modal, padx=20, pady=15)
        frm.pack(fill="both", expand=True)
        tk.Label(frm, text=cuenta["descripcion"], font=("Segoe UI", 12, "bold"),
                 wraplength=310, justify="left").pack(anchor="w")
        tk.Label(frm, text=f"Pendiente actual: ${pendiente:,.2f}").pack(anchor="w", pady=(2, 12))

        tk.Label(frm, text="Monto a abonar ($):").pack(anchor="w")
        e_monto = tk.Entry(frm)
        e_monto.pack(fill="x", pady=(0, 10))

        tk.Label(frm, text="Forma de pago:").pack(anchor="w")
        cb_forma = ttk.Combobox(frm, values=FORMAS_PAGO, state="readonly")
        cb_forma.current(0)
        cb_forma.pack(fill="x", pady=(0, 10))

        tk.Label(frm, text="Cuenta / caja de donde sale el dinero:").pack(anchor="w")
        cuentas_disponibles = db.get_nombres_cuentas()
        cb_cuenta = ttk.Combobox(frm, values=cuentas_disponibles, state="readonly")
        if cuentas_disponibles:
            cb_cuenta.current(0)
        cb_cuenta.pack(fill="x", pady=(0, 15))

        def guardar():
            try:
                monto = float(e_monto.get().replace(",", "."))
                if monto <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Ingresá un monto válido.", parent=modal)
                return
            if not cb_cuenta.get().strip():
                messagebox.showerror("Error", "Elegí de qué cuenta sale el dinero.", parent=modal)
                return
            if monto > pendiente + 0.01:
                if not messagebox.askyesno(
                    "Atención",
                    f"El monto (${monto:,.2f}) es mayor al pendiente (${pendiente:,.2f}). "
                    f"¿Continuar igual?",
                    parent=modal,
                ):
                    return
            hoy_iso = datetime.now().strftime("%Y-%m-%d")
            db.add_movimiento(hoy_iso, "gasto", TIPO_DEUDA_A_CATEGORIA.get(cuenta["tipo"], "Otros gastos"),
                               f"Abono a: {cuenta['descripcion']}",
                               cuenta["acreedor"] or "", monto,
                               cb_forma.get(), cb_cuenta.get().strip())
            db.abonar_cuenta_pagar(id_, monto)
            self.actualizar_tabla()
            self.actualizar_saldo()
            refrescar()
            modal.destroy()

        tk.Button(frm, text="Registrar abono", command=guardar,
                  bg="#3B82F6", fg="white", pady=8).pack(fill="x")

    # ---------------- MODAL: ANÁLISIS (GRÁFICOS DE TORTA) ----------------
    PERIODOS = ["Todo el historial", "Este mes", "Últimos 3 meses", "Últimos 6 meses", "Este año"]
    PALETA_GRAFICOS = ["#E5484D", "#F59E0B", "#4F8CFF", "#7C5CFC", "#2FA36B", "#E91E63",
                       "#0E9F8E", "#F97316", "#06B6D4", "#94A3B8", "#C084FC", "#84CC16"]
    MES_CORTO = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

    @staticmethod
    def _inicio_mes_atras(n):
        hoy = date.today()
        y, m = hoy.year, hoy.month - n
        while m <= 0:
            m += 12
            y -= 1
        return date(y, m, 1)

    def _rango_periodo(self, nombre):
        hoy = date.today()
        if nombre == "Este mes":
            return hoy.replace(day=1).isoformat(), hoy.isoformat()
        if nombre == "Últimos 3 meses":
            return self._inicio_mes_atras(2).isoformat(), hoy.isoformat()
        if nombre == "Últimos 6 meses":
            return self._inicio_mes_atras(5).isoformat(), hoy.isoformat()
        if nombre == "Este año":
            return date(hoy.year, 1, 1).isoformat(), hoy.isoformat()
        return None, None

    def modal_analisis(self):
        p = PALETA
        modal = Ventana(self)
        modal.configure(bg=p["bg"])
        modal.title("Análisis y gráficos")
        modal.geometry("900x660")
        modal.transient(self)
        modal.grab_set()

        cab = tk.Frame(modal, bg=p["bg"])
        cab.pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(cab, text="Análisis y gráficos", font=("Segoe UI", 15, "bold")).pack(side="left")
        cb = ttk.Combobox(cab, values=self.PERIODOS, state="readonly", width=18)
        cb.current(0)
        cb.pack(side="right")
        tk.Label(cab, text="Período:", fg=p["fg_muted"]).pack(side="right", padx=(0, 8))
        cuerpo = tk.Frame(modal, bg=p["bg"])
        cuerpo.pack(fill="both", expand=True)

        def construir(_=None):
            for w in cuerpo.winfo_children():
                w.destroy()
            desde, hasta = self._rango_periodo(cb.get())
            self._construir_analisis(cuerpo, desde, hasta)

        cb.bind("<<ComboboxSelected>>", construir)
        construir()

    def _construir_analisis(self, parent, desde, hasta):
        p = PALETA
        movs = db.get_movimientos(desde, hasta)
        ingresos = sum(m["monto"] for m in movs if m["tipo"] == "ingreso")
        gastos = sum(m["monto"] for m in movs if m["tipo"] == "gasto")
        prom = db.get_promedios_categoria(desde, hasta)
        meses = prom["meses"]

        kpis = tk.Frame(parent, bg=p["bg"])
        kpis.pack(fill="x", padx=16, pady=(8, 8))
        for i in range(4):
            kpis.grid_columnconfigure(i, weight=1, uniform="kpi")
        k1 = self._tarjeta(kpis, 0, "INGRESOS DEL PERÍODO", "#2FA36B")
        k2 = self._tarjeta(kpis, 1, "GASTOS DEL PERÍODO", "#E5484D")
        k3 = self._tarjeta(kpis, 2, "BALANCE DEL PERÍODO", "#4F8CFF")
        k4 = self._tarjeta(kpis, 3, "GASTO PROMEDIO MENSUAL", "#F59E0B")
        k1[0].config(text=dinero(ingresos), fg="#6fd69b")
        k1[1].config(text=f"{len([m for m in movs if m['tipo'] == 'ingreso'])} movimientos")
        k2[0].config(text=dinero(gastos), fg="#ff8f8f")
        k2[1].config(text=f"{len([m for m in movs if m['tipo'] == 'gasto'])} movimientos")
        k3[0].config(text=dinero(ingresos - gastos), fg="#6fd69b" if ingresos >= gastos else "#ff8f8f")
        k3[1].config(text="Ingresos − gastos")
        k4[0].config(text=dinero(gastos / meses))
        k4[1].config(text=f"En {meses} mes(es)")
        for k in (k1, k2, k3, k4):
            k[0].config(font=("Segoe UI", 15, "bold"))

        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        t_prom, t_evo, t_dist, t_res, t_dia = (tk.Frame(nb, bg=p["bg"]) for _ in range(5))
        nb.add(t_prom, text="Promedio por categoría")
        nb.add(t_evo, text="Evolución mensual")
        nb.add(t_dist, text="Distribución de gastos")
        nb.add(t_res, text="Resumen general")
        nb.add(t_dia, text="Gasto por día")

        self._dibujar_tabla_categorias(t_prom, prom)
        self._dibujar_evolucion_mensual(t_evo, db.get_resumen_mensual(desde, hasta, 12),
                                        gastos / meses if meses else 0)
        datos_dist = [(r["categoria"], r["total"], self.PALETA_GRAFICOS[i % len(self.PALETA_GRAFICOS)])
                      for i, r in enumerate(prom["filas"])]
        self._dibujar_torta(t_dist, datos_dist, "Gastos por categoría")
        self._dibujar_torta(t_res, [
            ("Ingresos", ingresos, "#2FA36B"),
            ("Gastos", gastos, "#E5484D"),
            ("Deudas pendientes", db.get_total_pendiente(), "#F59E0B"),
        ], "Distribución general")
        self._dibujar_barras_diarias(t_dia)

    def _canvas_con_scroll(self, parent, W):
        p = PALETA
        cont = tk.Frame(parent, bg=p["bg"])
        cont.pack(fill="both", expand=True, padx=6, pady=6)
        cv = tk.Canvas(cont, bg=p["tree_bg"], highlightthickness=0, width=W)
        sc = ttk.Scrollbar(cont, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sc.set)
        cv.pack(side="left", fill="both", expand=True)
        sc.pack(side="right", fill="y")
        cv.bind("<Enter>", lambda e: cv.bind_all("<MouseWheel>", lambda ev: cv.yview_scroll(int(-ev.delta / 120), "units")))
        cv.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))
        return cv

    def _dibujar_tabla_categorias(self, parent, datos):
        """Tabla con barras: por categoría, cantidad de movimientos, total,
        promedio por movimiento, promedio mensual y % del gasto total."""
        p = PALETA
        filas = datos["filas"]
        W, HEAD, RH = 800, 36, 34
        cv = self._canvas_con_scroll(parent, W)
        if not filas:
            cv.create_text(W / 2, 80, text="No hay gastos en este período.", fill=p["fg_muted"],
                           font=("Segoe UI", 11))
            return
        X_N, X_TOT, X_PM, X_MES, X_BAR, ANCHO_BAR = 296, 412, 540, 662, 684, 78
        for x, texto, anc in ((16, "Categoría", "w"), (X_N, "Mov.", "e"), (X_TOT, "Total", "e"),
                              (X_PM, "Prom. por mov.", "e"), (X_MES, "Prom. mensual", "e"),
                              (X_BAR, "% del gasto", "w")):
            cv.create_text(x, HEAD / 2, text=texto, anchor=anc, fill=p["fg_muted"], font=("Segoe UI", 9, "bold"))
        cv.create_line(0, HEAD, W, HEAD, fill=p["line"])
        for i, f in enumerate(filas):
            y0 = HEAD + i * RH
            cv.create_rectangle(0, y0, W, y0 + RH, fill="#171a26" if i % 2 == 0 else "#1c2030", outline="")
            yc = y0 + RH / 2
            color = self.PALETA_GRAFICOS[i % len(self.PALETA_GRAFICOS)]
            cv.create_rectangle(8, yc - 9, 12, yc + 9, fill=color, outline="")
            cv.create_text(20, yc, text=f["categoria"], anchor="w", fill=p["fg"], font=("Segoe UI", 10, "bold"))
            cv.create_text(X_N, yc, text=str(f["n"]), anchor="e", fill=p["fg_muted"], font=("Segoe UI", 10))
            cv.create_text(X_TOT, yc, text=dinero(f["total"]), anchor="e", fill=p["fg"], font=("Segoe UI", 10))
            cv.create_text(X_PM, yc, text=dinero(f["prom_mov"]), anchor="e", fill=p["fg_muted"], font=("Segoe UI", 10))
            cv.create_text(X_MES, yc, text=dinero(f["prom_mensual"]), anchor="e", fill="#F59E0B", font=("Segoe UI", 10, "bold"))
            cv.create_rectangle(X_BAR, yc - 5, X_BAR + ANCHO_BAR, yc + 5, fill="#232838", outline="")
            cv.create_rectangle(X_BAR, yc - 5, X_BAR + max(3, ANCHO_BAR * f["pct"] / 100), yc + 5, fill=color, outline="")
            cv.create_text(X_BAR + ANCHO_BAR + 8, yc, text=f"{f['pct']:.1f}%", anchor="w", fill=p["fg"], font=("Segoe UI", 9))
        yf = HEAD + len(filas) * RH
        cv.create_line(0, yf, W, yf, fill=p["line"])
        cv.create_text(16, yf + 22, anchor="w", fill="white", font=("Segoe UI", 10, "bold"),
                       text=f"Total gastado: {dinero(datos['total'])}   ·   Promedio mensual: "
                            f"{dinero(datos['total'] / datos['meses'])}   ·   Período: {datos['meses']} mes(es)")
        cv.create_text(16, yf + 44, anchor="w", fill=p["fg_muted"], font=("Segoe UI", 9),
                       text="Promedio mensual = total de la categoría ÷ meses del período (cuenta también los meses sin gasto).")
        cv.configure(scrollregion=(0, 0, W, yf + 64))

    def _dibujar_evolucion_mensual(self, parent, datos, prom_gasto):
        p = PALETA
        W, H = 830, 330
        cv = tk.Canvas(parent, width=W, height=H, bg=p["tree_bg"], highlightthickness=0)
        cv.pack(padx=6, pady=8)
        if not datos:
            cv.create_text(W / 2, H / 2, text="Sin movimientos en este período.", fill=p["fg_muted"],
                           font=("Segoe UI", 11))
            return
        left, right, top, base = 56, W - 16, 44, H - 62
        maxv = max([max(i, g) for _, i, g in datos] + [prom_gasto, 1])
        for k in range(5):
            y = base - (base - top) * k / 4
            cv.create_line(left, y, right, y, fill=p["line"])
            cv.create_text(left - 6, y, text=corto(maxv * k / 4), anchor="e", fill=p["fg_muted"], font=("Segoe UI", 8))
        n = len(datos)
        grupo = (right - left) / n
        bw = min(34, grupo * 0.4)
        for idx, (ym, ing, gas) in enumerate(datos):
            cx = left + grupo * (idx + 0.5)
            for x0, x1, v, color in ((cx - bw, cx - 1, ing, "#2FA36B"), (cx + 1, cx + bw, gas, "#E5484D")):
                y = base - (v / maxv) * (base - top)
                if v > 0:
                    cv.create_rectangle(x0, y, x1, base, fill=color, outline="")
                    cv.create_text((x0 + x1) / 2, y - 8, text=corto(v), fill=p["fg"], font=("Segoe UI", 8))
            a, m = ym.split("-")
            cv.create_text(cx, base + 14, text=f"{self.MES_CORTO[int(m) - 1]} {a[2:]}", fill=p["fg_muted"], font=("Segoe UI", 9))
            neto = ing - gas
            cv.create_text(cx, base + 32, text=("+" if neto >= 0 else "−") + corto(abs(neto)),
                           fill="#6fd69b" if neto >= 0 else "#ff8f8f", font=("Segoe UI", 9, "bold"))
        cv.create_text(left - 6, base + 32, text="Neto", anchor="e", fill=p["fg_muted"], font=("Segoe UI", 8))
        ya = base - (prom_gasto / maxv) * (base - top)
        cv.create_line(left, ya, right, ya, fill="#F59E0B", dash=(6, 4), width=2)
        cv.create_text(right, ya - 9, text=f"Gasto prom. mensual {dinero(prom_gasto)}", anchor="e",
                       fill="#F59E0B", font=("Segoe UI", 9, "bold"))
        for i, (txt, color) in enumerate((("Ingresos", "#2FA36B"), ("Gastos", "#E5484D"))):
            cv.create_rectangle(left + i * 90, 14, left + i * 90 + 12, 26, fill=color, outline="")
            cv.create_text(left + i * 90 + 18, 20, text=txt, anchor="w", fill=p["fg"], font=("Segoe UI", 9))

    def _dibujar_torta(self, parent, datos, titulo):
        datos = [d for d in datos if d[1] and d[1] > 0]
        tk.Label(parent, text=titulo, font=("Segoe UI", 12, "bold")).pack(pady=(12, 5))
        cont = tk.Frame(parent)
        cont.pack(fill="both", expand=True, padx=10, pady=10)
        total = sum(d[1] for d in datos)

        canvas = tk.Canvas(cont, width=260, height=260, bg=PALETA["tree_bg"], highlightthickness=0)
        canvas.pack(side="left", padx=10)
        if total <= 0:
            canvas.create_text(130, 130, text="Sin datos todavía", fill=PALETA["fg_muted"])
        else:
            x0, y0, x1, y1 = 10, 10, 250, 250
            start = 90
            for _, valor, color in datos:
                extent = 360 * (valor / total)
                canvas.create_arc(x0, y0, x1, y1, start=start, extent=-extent,
                                   fill=color, outline=PALETA["bg"], width=2)
                start -= extent

        leyenda = tk.Frame(cont)
        leyenda.pack(side="left", fill="y", padx=15, anchor="n")
        if not datos:
            tk.Label(leyenda, text="No hay movimientos para graficar todavía.").pack(anchor="w")
        for nombre, valor, color in datos:
            pct = (valor / total * 100) if total else 0
            fila = tk.Frame(leyenda)
            fila.pack(anchor="w", pady=3)
            tk.Canvas(fila, width=14, height=14, bg=color, highlightthickness=0).pack(side="left", padx=(0, 6))
            tk.Label(fila, text=f"{nombre}: ${valor:,.2f} ({pct:.1f}%)").pack(side="left")

    def _dibujar_barras_diarias(self, parent):
        p = PALETA
        st = db.get_stats_gasto_diario()
        datos = db.get_gasto_por_dia(14)
        tk.Label(parent, text="Gasto por día (últimos 14 días)", font=("Segoe UI", 13, "bold")).pack(pady=(14, 2))
        tk.Label(parent, text=f"Promedio diario: {dinero(st['promedio'])}   ·   Últimos 7 días: "
                              f"{dinero(st['prom7'])}   ·   Total gastado: {dinero(st['total'])} en {st['dias']} día(s)",
                 font=("Segoe UI", 10), fg=p["fg_muted"]).pack()
        W, H = 800, 300
        cv = tk.Canvas(parent, width=W, height=H, bg=p["tree_bg"], highlightthickness=0)
        cv.pack(pady=10)
        maxv = max([v for _, v in datos] + [st["promedio"], 1])
        base, tope, n = H - 46, 36, len(datos)
        bw = (W - 40) / n
        for i, (dia, v) in enumerate(datos):
            x0, x1 = 20 + i * bw + 5, 20 + (i + 1) * bw - 5
            y0 = base - (v / maxv) * (base - tope)
            cv.create_rectangle(x0, y0, x1, base, fill="#E5484D" if v > st["promedio"] else "#4F8CFF", outline="")
            cv.create_text((x0 + x1) / 2, base + 16, text=dia.strftime("%d/%m"), fill=p["fg_muted"], font=("Segoe UI", 9))
            if v > 0:
                cv.create_text((x0 + x1) / 2, y0 - 10, text=f"{v/1000:.1f}k", fill=p["fg"], font=("Segoe UI", 9))
        ya = base - (st["promedio"] / maxv) * (base - tope)
        cv.create_line(20, ya, W - 20, ya, fill="#F59E0B", dash=(6, 4), width=2)
        cv.create_text(24, ya - 12, text=f"Promedio {dinero(st['promedio'])}", fill="#F59E0B", anchor="w", font=("Segoe UI", 10, "bold"))
        tk.Label(parent, text="Rojo = día por encima del promedio · Azul = por debajo",
                 font=("Segoe UI", 10), fg=p["fg_muted"]).pack()

    # ---------------- EXPORTAR / IMPORTAR (migración de PC) ----------------
    def exportar_datos(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialfile="respaldo_contable.json",
        )
        if not path:
            return
        db.export_data(path)
        messagebox.showinfo(
            "Listo",
            f"Datos exportados a:\n{path}\n\nGuardá este archivo para restaurarlo en otra PC "
            f"(por ejemplo tu equipo Ryzen 7) cuando reinstales el sistema.",
        )

    def importar_datos(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        modo = messagebox.askyesnocancel(
            "Modo de importación",
            "¿Querés FUSIONAR estos datos con los existentes?\n\n"
            "Sí = Fusionar (agrega sin borrar lo que ya hay)\n"
            "No = Reemplazar todo (borra los movimientos y deudas actuales)\n"
            "Cancelar = Abortar",
        )
        if modo is None:
            return
        db.import_data(path, "fusionar" if modo else "reemplazar")
        self.actualizar_tabla()
        self.actualizar_saldo()
        messagebox.showinfo("Listo", "Datos importados correctamente.")

    # ---------------- MODAL: GESTIONAR CUENTAS ----------------
    def modal_gestionar_cuentas(self):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Gestionar cuentas")
        modal.geometry("680x500")
        modal.transient(self)
        modal.grab_set()

        tk.Label(modal, text="Cuentas / cajas (efectivo, bancos, billeteras)",
                 font=("Segoe UI", 13, "bold")).pack(pady=(10, 5))

        tabla_frame = tk.Frame(modal)
        tabla_frame.pack(fill="both", expand=True, padx=10, pady=5)
        cols = ("nombre", "saldo_inicial", "saldo_actual")
        tree = ttk.Treeview(tabla_frame, columns=cols, show="headings")
        encab = {"nombre": "Cuenta", "saldo_inicial": "Saldo inicial", "saldo_actual": "Saldo actual"}
        for c in cols:
            tree.heading(c, text=encab[c])
            tree.column(c, width=170)
        tree.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(tabla_frame, orient="vertical", command=tree.yview)
        scroll.pack(side="right", fill="y")
        tree.configure(yscroll=scroll.set)

        def refrescar():
            for i in tree.get_children():
                tree.delete(i)
            for c in db.get_saldos_cuentas():
                iid = str(c["id"]) if c["id"] is not None else "sin_asignar"
                tree.insert("", "end", iid=iid, values=(
                    c["nombre"], f"${c['saldo_inicial']:,.2f}", f"${c['saldo_actual']:,.2f}",
                ))

        def nueva_cuenta():
            self._modal_cuenta_form(None, refrescar)

        def editar_cuenta():
            sel = tree.selection()
            if not sel or sel[0] == "sin_asignar":
                messagebox.showwarning("Atención", "Seleccioná una cuenta editable de la tabla.", parent=modal)
                return
            self._modal_cuenta_form(int(sel[0]), refrescar)

        def eliminar_cuenta():
            sel = tree.selection()
            if not sel or sel[0] == "sin_asignar":
                messagebox.showwarning("Atención", "Seleccioná una cuenta editable de la tabla.", parent=modal)
                return
            if messagebox.askyesno(
                "Confirmar",
                "¿Eliminar esta cuenta?\n\n"
                "Los movimientos ya cargados con esta cuenta no se borran, pero "
                "van a figurar como 'Sin cuenta asignada' hasta que los edites.",
                parent=modal,
            ):
                db.delete_cuenta(int(sel[0]))
                refrescar()
                self.actualizar_saldo()

        botones = tk.Frame(modal, pady=8)
        botones.pack(fill="x")
        tk.Button(botones, text="+ Nueva cuenta", command=nueva_cuenta,
                  bg="#2FA36B", fg="white", padx=8, pady=6).pack(side="left", padx=5)
        tk.Button(botones, text="Editar", command=editar_cuenta,
                  bg="#4F6BED", fg="white", padx=8, pady=6).pack(side="left", padx=5)
        tk.Button(botones, text="Eliminar", command=eliminar_cuenta,
                  bg="#475569", fg="white", padx=8, pady=6).pack(side="left", padx=5)
        tk.Button(botones, text="Reasignar movimientos sueltos",
                  command=lambda: self._modal_reasignar_huerfanos(refrescar),
                  bg="#F59E0B", fg="white", padx=8, pady=6).pack(side="left", padx=5)

        tk.Label(
            modal,
            text='"Sin cuenta asignada" no es una cuenta: son movimientos con un texto '
                 'de cuenta viejo que ya no coincide con ninguna de arriba. Usá '
                 '"Reasignar movimientos sueltos" para mandarlos a la cuenta que corresponda.',
            font=("Segoe UI", 10), fg=PALETA["fg_muted"], justify="left", wraplength=520,
        ).pack(padx=10, pady=(0, 8), anchor="w")

        refrescar()

    def _modal_reasignar_huerfanos(self, refrescar_padre):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Reasignar movimientos sueltos")
        modal.geometry("680x500")
        modal.transient(self)
        modal.grab_set()

        tk.Label(modal, text="Textos de cuenta que no coinciden con ninguna cuenta actual",
                 font=("Segoe UI", 12, "bold"), wraplength=520, justify="left").pack(pady=(10, 5), padx=10)

        tabla_frame = tk.Frame(modal)
        tabla_frame.pack(fill="both", expand=True, padx=10, pady=5)
        cols = ("valor", "cantidad", "neto")
        tree = ttk.Treeview(tabla_frame, columns=cols, show="headings", height=8)
        encab = {"valor": "Texto de cuenta (viejo)", "cantidad": "Movimientos", "neto": "Suma neta"}
        for c in cols:
            tree.heading(c, text=encab[c])
            tree.column(c, width=170)
        tree.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(tabla_frame, orient="vertical", command=tree.yview)
        scroll.pack(side="right", fill="y")
        tree.configure(yscroll=scroll.set)

        def refrescar_lista():
            for i in tree.get_children():
                tree.delete(i)
            for r in db.get_valores_cuenta_huerfanos():
                tree.insert("", "end", iid=r["valor"], values=(
                    r["valor"], r["cantidad"], f"${r['neto']:,.2f}",
                ))

        abajo = tk.Frame(modal, pady=10)
        abajo.pack(fill="x", padx=10)
        tk.Label(abajo, text="Mandar el seleccionado a la cuenta:").pack(side="left", padx=(0, 8))
        cb_destino = ttk.Combobox(abajo, values=db.get_nombres_cuentas(), state="readonly", width=22)
        if db.get_nombres_cuentas():
            cb_destino.current(0)
        cb_destino.pack(side="left", padx=(0, 8))

        def reasignar():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Atención", "Seleccioná un texto de cuenta de la lista.", parent=modal)
                return
            destino = cb_destino.get().strip()
            if not destino:
                messagebox.showwarning("Atención", "Elegí a qué cuenta mandarlos.", parent=modal)
                return
            valor_viejo = sel[0]
            if not messagebox.askyesno(
                "Confirmar",
                f"¿Mover TODOS los movimientos con cuenta '{valor_viejo}' a '{destino}'?",
                parent=modal,
            ):
                return
            db.reasignar_cuenta_masivo(valor_viejo, destino)
            refrescar_lista()
            refrescar_padre()
            self.actualizar_saldo()
            self.actualizar_tabla()

        tk.Button(abajo, text="Reasignar", command=reasignar,
                  bg="#2FA36B", fg="white", padx=10, pady=4).pack(side="left")

        refrescar_lista()

    def _modal_cuenta_form(self, cuenta_id, refrescar):
        """cuenta_id=None -> crear cuenta nueva. Si no, edita esa cuenta."""
        existente = None
        if cuenta_id is not None:
            existente = next((c for c in db.get_cuentas() if c["id"] == cuenta_id), None)

        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Nueva cuenta" if existente is None else "Editar cuenta")
        modal.geometry("420x330")
        modal.transient(self)
        modal.grab_set()
        modal.resizable(False, False)

        frm = tk.Frame(modal, padx=20, pady=15)
        frm.pack(fill="both", expand=True)

        tk.Label(frm, text="Nombre de la cuenta:").pack(anchor="w")
        e_nombre = tk.Entry(frm)
        e_nombre.pack(fill="x", pady=(0, 10))
        if existente:
            e_nombre.insert(0, existente["nombre"])

        etiqueta_saldo = "Saldo inicial ($):" if existente is None else "Saldo inicial ($) — ajustar con cuidado:"
        tk.Label(frm, text=etiqueta_saldo).pack(anchor="w")
        e_saldo = tk.Entry(frm)
        e_saldo.insert(0, f"{existente['saldo_inicial']:g}" if existente else "0")
        e_saldo.pack(fill="x", pady=(0, 10))

        if existente:
            tk.Label(frm, text="Cambiar el saldo inicial no crea un movimiento;\n"
                                "es un ajuste directo del punto de partida.",
                     font=("Segoe UI", 10), fg=PALETA["fg_muted"], justify="left").pack(anchor="w", pady=(0, 10))

        def guardar():
            nombre = e_nombre.get().strip()
            if not nombre:
                messagebox.showerror("Error", "El nombre no puede quedar vacío.", parent=modal)
                return
            try:
                saldo = float(e_saldo.get().replace(",", "."))
            except ValueError:
                messagebox.showerror("Error", "El saldo inicial debe ser un número.", parent=modal)
                return
            try:
                if existente:
                    db.rename_cuenta(existente["id"], nombre, saldo)
                else:
                    db.add_cuenta(nombre, saldo)
            except Exception:
                messagebox.showerror("Error", "Ya existe una cuenta con ese nombre.", parent=modal)
                return
            refrescar()
            self.actualizar_saldo()
            modal.destroy()

        tk.Button(frm, text="Guardar", command=guardar,
                  bg="#2FA36B", fg="white", pady=8).pack(fill="x", pady=(5, 0))

    # ---------------- MODAL: CATEGORÍAS ----------------
    def modal_categorias(self):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Categorías")
        modal.geometry("760x540")
        modal.transient(self)
        modal.grab_set()
        tk.Label(modal, text="Categorías en uso", font=("Segoe UI", 13, "bold")).pack(pady=(14, 2))
        tk.Label(modal, text="Para unificar o renombrar: seleccioná una o varias (Ctrl + clic) y usá el botón. "
                             "Se corrige en todos los movimientos.", font=("Segoe UI", 10),
                 fg=PALETA["fg_muted"]).pack()
        tf = tk.Frame(modal)
        tf.pack(fill="both", expand=True, padx=16, pady=10)
        cols = ("tipo", "categoria", "n", "total")
        tree = ttk.Treeview(tf, columns=cols, show="headings")
        for c, t, w in (("tipo", "Tipo", 90), ("categoria", "Categoría", 280), ("n", "Movimientos", 120),
                        ("total", "Total", 150)):
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="e" if c in ("n", "total") else "w")
        tree.pack(fill="both", expand=True, side="left")
        sc = ttk.Scrollbar(tf, orient="vertical", command=tree.yview)
        sc.pack(side="right", fill="y")
        tree.configure(yscroll=sc.set)

        def refrescar():
            for i in tree.get_children():
                tree.delete(i)
            for r in db.get_categorias_resumen():
                tree.insert("", "end", iid=f"{r['tipo']}|{r['categoria']}", values=(
                    r["tipo"].capitalize(), r["categoria"], r["n"], dinero(r["total"])))

        def renombrar():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Atención", "Seleccioná al menos una categoría.", parent=modal)
                return
            tipos = {i.split("|", 1)[0] for i in sel}
            if len(tipos) > 1:
                messagebox.showwarning("Atención", "No mezcles ingresos con gastos.", parent=modal)
                return
            inicial = sel[0].split("|", 1)[1]
            nuevo = simpledialog.askstring("Renombrar / unificar", "Nombre final de la categoría:",
                                           initialvalue=inicial, parent=modal)
            if nuevo and nuevo.strip():
                for i in sel:
                    t, c = i.split("|", 1)
                    db.rename_categoria(t, c, nuevo)
                refrescar()
                self.actualizar_tabla()

        bt = tk.Frame(modal)
        bt.pack(fill="x", padx=16, pady=(0, 14))
        tk.Button(bt, text="Renombrar / unificar", command=renombrar, bg="#4F6BED", fg="white").pack(side="left")
        tk.Button(bt, text="Cerrar", command=modal.destroy, bg="#475569", fg="white").pack(side="right")
        refrescar()

    # ---------------- MODAL: BENEFICIARIOS ----------------
    def modal_beneficiarios(self):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Beneficiarios (a quién se paga)")
        modal.geometry("860x560")
        modal.transient(self)
        modal.grab_set()
        tk.Label(modal, text="Beneficiarios guardados", font=("Segoe UI", 14, "bold")).pack(pady=(16, 2))
        tk.Label(modal, text="Para unificar duplicados: Ctrl + clic en cada uno, luego 'Unificar seleccionados'.", font=("Segoe UI", 10),
                 fg=PALETA["fg_muted"]).pack()
        tf = tk.Frame(modal)
        tf.pack(fill="both", expand=True, padx=16, pady=12)
        cols = ("nombre", "veces", "categoria", "forma_pago", "cuenta")
        tree = ttk.Treeview(tf, columns=cols, show="headings")
        for c, t, w in (("nombre", "Nombre", 290), ("veces", "Usos", 70), ("categoria", "Categoría habitual", 160),
                        ("forma_pago", "Forma de pago", 150), ("cuenta", "Cuenta", 150)):
            tree.heading(c, text=t)
            tree.column(c, width=w)
        tree.pack(fill="both", expand=True, side="left")
        sc = ttk.Scrollbar(tf, orient="vertical", command=tree.yview)
        sc.pack(side="right", fill="y")
        tree.configure(yscroll=sc.set)

        def refrescar():
            for i in tree.get_children():
                tree.delete(i)
            for b in db.get_beneficiarios():
                tree.insert("", "end", iid=str(b["id"]), values=(
                    b["nombre"], b["veces"], b["categoria"] or "-", b["forma_pago"] or "-", b["cuenta"] or "-"))

        def renombrar():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Atención", "Seleccioná un beneficiario.", parent=modal)
                return
            actual = tree.item(sel[0], "values")[0]
            nuevo = simpledialog.askstring("Renombrar / unificar", "Nuevo nombre:",
                                           initialvalue=actual, parent=modal)
            if nuevo and nuevo.strip():
                db.rename_beneficiario(int(sel[0]), nuevo)
                refrescar()
                self.actualizar_tabla()

        def unificar():
            sel = tree.selection()
            if len(sel) < 2:
                messagebox.showwarning("Atención", "Seleccioná 2 o más (mantené Ctrl y hacé clic en cada uno).",
                                       parent=modal)
                return
            mejor = max(sel, key=lambda i: int(tree.item(i, "values")[1]))
            nuevo = simpledialog.askstring("Unificar", f"Nombre final para los {len(sel)} seleccionados:",
                                           initialvalue=tree.item(mejor, "values")[0], parent=modal)
            if nuevo and nuevo.strip():
                for i in sel:
                    db.rename_beneficiario(int(i), nuevo)
                refrescar()
                self.actualizar_tabla()

        def eliminar():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Atención", "Seleccioná un beneficiario.", parent=modal)
                return
            if messagebox.askyesno("Confirmar", "¿Quitar de las sugerencias?\n\nLos movimientos ya "
                                   "cargados no se modifican.", parent=modal):
                db.delete_beneficiario(int(sel[0]))
                refrescar()

        bt = tk.Frame(modal)
        bt.pack(fill="x", padx=16, pady=(0, 16))
        tk.Button(bt, text="Unificar seleccionados", command=unificar, bg="#2FA36B", fg="white").pack(side="left")
        tk.Button(bt, text="Renombrar", command=renombrar, bg="#4F6BED", fg="white").pack(side="left", padx=10)
        tk.Button(bt, text="Quitar de sugerencias", command=eliminar, bg="#475569", fg="white").pack(side="left", padx=10)
        tk.Button(bt, text="Cerrar", command=modal.destroy, bg="#475569", fg="white").pack(side="right")
        refrescar()

    # ---------------- MODAL: CALCULADORA ----------------
    def modal_calculadora(self):
        modal = Ventana(self)
        modal.configure(bg=PALETA["bg"])
        modal.title("Calculadora")
        modal.resizable(False, False)
        modal.transient(self)

        var_pantalla = tk.StringVar(value="0")
        pantalla = tk.Entry(modal, textvariable=var_pantalla, justify="right",
                             font=("Segoe UI", 19), bd=4, relief="sunken",
                             bg=PALETA["entry_bg"], fg=PALETA["fg"])
        pantalla.grid(row=0, column=0, columnspan=4, sticky="nsew", padx=8, pady=8, ipady=8)

        estado = {"expresion": ""}

        def refrescar_pantalla():
            var_pantalla.set(estado["expresion"] if estado["expresion"] else "0")

        def presionar(caracter):
            # Solo se aceptan dígitos, punto y los operadores básicos: nada de
            # texto arbitrario llega nunca a evaluarse.
            estado["expresion"] += caracter
            refrescar_pantalla()

        def borrar_todo():
            estado["expresion"] = ""
            refrescar_pantalla()

        def borrar_uno():
            estado["expresion"] = estado["expresion"][:-1]
            refrescar_pantalla()

        def calcular():
            expr = estado["expresion"].strip()
            if not expr:
                return
            if not all(ch in "0123456789.+-*/() " for ch in expr):
                messagebox.showerror("Error", "Solo se permiten números y + - * / ( )", parent=modal)
                return
            try:
                resultado = eval(expr, {"__builtins__": {}}, {})
            except ZeroDivisionError:
                messagebox.showerror("Error", "No se puede dividir por cero.", parent=modal)
                return
            except Exception:
                messagebox.showerror("Error", "Esa cuenta no es válida.", parent=modal)
                return
            estado["expresion"] = self._formatear_numero(resultado)
            refrescar_pantalla()

        botones = [
            ("C", borrar_todo, "#475569"), ("⌫", borrar_uno, "#475569"),
            ("(", lambda: presionar("("), "#475569"), (")", lambda: presionar(")"), "#475569"),
            ("7", lambda: presionar("7"), None), ("8", lambda: presionar("8"), None),
            ("9", lambda: presionar("9"), None), ("/", lambda: presionar("/"), "#F59E0B"),
            ("4", lambda: presionar("4"), None), ("5", lambda: presionar("5"), None),
            ("6", lambda: presionar("6"), None), ("*", lambda: presionar("*"), "#F59E0B"),
            ("1", lambda: presionar("1"), None), ("2", lambda: presionar("2"), None),
            ("3", lambda: presionar("3"), None), ("-", lambda: presionar("-"), "#F59E0B"),
            ("0", lambda: presionar("0"), None), (".", lambda: presionar("."), None),
            ("=", calcular, "#2FA36B"), ("+", lambda: presionar("+"), "#F59E0B"),
        ]
        fila, col = 1, 0
        for texto, accion, color in botones:
            tk.Button(modal, text=texto, command=accion, width=5, height=2,
                      bg=color or PALETA["bg_alt"], fg="white", relief="flat",
                      ).grid(row=fila, column=col, padx=3, pady=3)
            col += 1
            if col > 3:
                col = 0
                fila += 1

        modal.bind("<Return>", lambda e: calcular())
        modal.bind("<BackSpace>", lambda e: borrar_uno())

    @staticmethod
    def _formatear_numero(valor):
        if isinstance(valor, float) and valor.is_integer():
            valor = int(valor)
        return str(valor)

    # ---------------- CAMBIAR CONTRASEÑA / CLAVE DE RECUPERACIÓN ----------------
    def modal_cambiar_password(self):
        p = PALETA
        modal = Ventana(self)
        modal.configure(bg=p["bg"])
        modal.title("Contraseña y recuperación")
        modal.geometry("460x560")
        modal.transient(self)
        modal.grab_set()
        modal.resizable(False, False)

        frm = tk.Frame(modal, padx=28, pady=18)
        frm.pack(fill="both", expand=True)
        tk.Label(frm, text="Contraseña y recuperación", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 12))
        tk.Label(frm, text="Contraseña actual:").pack(anchor="w")
        e_actual = tk.Entry(frm, show="*")
        e_actual.pack(fill="x", pady=(2, 8))
        tk.Label(frm, text="Nueva contraseña:").pack(anchor="w")
        e_nueva = tk.Entry(frm, show="*")
        e_nueva.pack(fill="x", pady=(2, 8))
        tk.Label(frm, text="Repetir nueva contraseña:").pack(anchor="w")
        e_rep = tk.Entry(frm, show="*")
        e_rep.pack(fill="x", pady=(2, 8))

        def guardar():
            if not auth.verificar_login(self.usuario_actual, e_actual.get()):
                messagebox.showerror("Error", "La contraseña actual es incorrecta.", parent=modal)
                return
            if len(e_nueva.get()) < 4:
                messagebox.showerror("Error", "La nueva contraseña es muy corta (mínimo 4).", parent=modal)
                return
            if e_nueva.get() != e_rep.get():
                messagebox.showerror("Error", "Las contraseñas nuevas no coinciden.", parent=modal)
                return
            auth.cambiar_password(e_nueva.get())
            messagebox.showinfo("Listo", "Contraseña actualizada.", parent=modal)
            modal.destroy()

        tk.Button(frm, text="Actualizar contraseña", command=guardar, bg="#475569", fg="white",
                  activebackground="#475569", activeforeground="white", pady=7).pack(fill="x", pady=(6, 14))

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=4)
        tk.Label(frm, text="Clave de recuperación", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 2))
        activa = auth.tiene_clave_recuperacion()
        tk.Label(frm, text="Estado: " + ("activa" if activa else "NO generada todavía"),
                 fg="#6fd69b" if activa else "#F59E0B").pack(anchor="w")
        tk.Label(frm, wraplength=400, justify="left", fg=p["fg_muted"],
                 text="Sirve para entrar si olvidás la contraseña. Generar una nueva invalida la anterior. "
                      "Se pide la contraseña actual (campo de arriba).").pack(anchor="w", pady=(2, 8))

        def nueva_clave():
            if not auth.verificar_login(self.usuario_actual, e_actual.get()):
                messagebox.showerror("Error", "Escribí tu contraseña actual en el primer campo para generar la clave.", parent=modal)
                return
            clave = auth.generar_clave_recuperacion()
            modal.destroy()
            self._mostrar_clave_recuperacion(clave)

        tk.Button(frm, text="Generar nueva clave de recuperación" if activa else "Generar clave de recuperación",
                  command=nueva_clave, bg="#B45309", fg="white", activebackground="#B45309",
                  activeforeground="white", pady=7).pack(fill="x")

