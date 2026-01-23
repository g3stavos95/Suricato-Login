#!/usr/bin/env python3
# coding: utf-8
"""
autologin.py — Documentação (v1.1)
Autor: Gustavo Pires
Data: 2026-01-23

IMPORTANTE
- Esta versão (v1.1) consolida melhorias de segurança, robustez e UX implementadas.
- O objetivo é manter o comportamento do app (tray + F12) e elevar a qualidade “profissional”.

Visão geral
- App residente (system tray) que preenche usuário/senha ao pressionar F12.
- Credenciais ficam em {"usuario", "senha_enc", "updated_at"} dentro de um JSON.
- A senha é criptografada com Fernet usando chave derivada de uma “senha mestra”.
- Um lock impede múltiplas instâncias simultâneas.
- No Linux usa ~/.config/suricato_autologin; no Windows usa %APPDATA%\\SuricatoAutoLogin.

Manutenção rápida
- Ponto de entrada: main()
- Setup/Login: perform_login_or_setup()
- Captura de tecla: start_keyboard_listener() + type_credentials()
- Tray/menus: run_tray_icon() + show_about()
- Single instance: SingleInstanceGuard + acquire_single_instance_or_exit()
- Criptografia: save_credentials() / load_credentials()

============================================================
Changelog / Melhorias implementadas nesta v1.1 (consolidado)
============================================================

1) Instância única (robusto e sólido)
- Windows: adicionada barreira por Named Mutex (CreateMutexW) + lockfile.
- Linux: lockfile com fcntl.flock (LOCK_EX | LOCK_NB).
- Mantém handle aberto e libera em atexit + tentativa extra via signal handlers (Linux).

2) UX / Foco nos dialogs (setup/login)
- Corrigido “perder foco” ao digitar usuário/senha/senha mestra:
  - Tkinter com: topmost + lift + focus_force + grab_set (modal)
  - Reforço via after() e recuperação em FocusOut com throttle
- No Linux, flags melhores para yad: --center --on-top --focus

3) GUI cross-platform (mais resiliente)
- Linux: preferir yad; se não existir, usar zenity; fallback Tkinter.
- Mensagens e inputs passam por wrappers gui_info/gui_error/gui_entry/gui_password.

4) Persistência mais segura e confiavel.
- Escrita atômica do JSON (arquivo .tmp + os.replace).
- chmod 600 no Linux (quando possível), reduz exposição do arquivo.

5) Criptografia fortalecida (compatível com legado)
- Novo formato: PBKDF2-HMAC-SHA256 (salt + iterations) -> Fernet.
- Compatibilidade: se config antigo não tiver kdf/salt/iterations, usa modo legado SHA256 direto.

6) “Sobre” mais profissional
- Mostra ícone + Nome + Versão + Autor (Gustavo Pires) + atalho F12.
- Linux: yad com --image quando possível; fallback Tkinter com imagem.

7) Encerramento limpo
- “Sair” para listener imediatamente e para o ícone tray.
- Handlers SIGINT/SIGTERM/SIGHUP no Linux para reduzir travas em encerramentos.

============================================================
"""

import os
import sys
import json
import time
import threading
import base64
import hashlib
import platform
import atexit
import logging
import subprocess
import signal
from pathlib import Path
from typing import Optional, Tuple

# Dependências externas
import pyautogui
from pynput import keyboard
from cryptography.fernet import Fernet, InvalidToken
import pystray
from PIL import Image

# ---------------- CONSTANTES E CONFIGURAÇÕES ----------------
APP_NAME = "Suricato AutoLogin"
APP_SLUG = "SuricatoAutoLogin"
APP_AUTHOR = "Gustavo Pires"
__version__ = "1.1"
COOLDOWN_S = 1.5

pyautogui.FAILSAFE = True

_stop_event = threading.Event()
_listener = None
_last_trigger_time = 0.0

# Para parar listener imediatamente
_listener_ref = {"listener": None}

# ---------------- SISTEMA DE LOGS E PATHS ----------------
def is_windows() -> bool:
    return platform.system().lower().startswith("win")


def is_linux() -> bool:
    return platform.system().lower().startswith("linux")


def get_base_dir() -> Path:
    if is_windows():
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(appdata) / APP_SLUG
    else:
        base = Path.home() / ".config" / "suricato_autologin"
    base.mkdir(parents=True, exist_ok=True)
    return base


BASE_DIR = get_base_dir()
CONFIG_FILE = BASE_DIR / "autologin.json"
LOCK_FILE = BASE_DIR / "autologin.lock"
LOG_FILE = BASE_DIR / "autologin.log"

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8",
)

# ---------------- EMPACOTAMENTO (PyInstaller) ----------------
def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


def get_external_icon_path() -> Path:
    return BASE_DIR / "autologin.png"


ICON_EXTERNAL_PATH = get_external_icon_path()
ICON_EMBED_NAME = "autologin.png"


def get_icon_path() -> str:
    if ICON_EXTERNAL_PATH.exists():
        return str(ICON_EXTERNAL_PATH)

    embedded = resource_path(ICON_EMBED_NAME)
    if os.path.exists(embedded):
        return embedded

    return ""


def load_icon_image() -> Image.Image:
    icon_path = get_icon_path()
    if not icon_path:
        return Image.new("RGBA", (64, 64), (40, 40, 40, 255))
    try:
        img = Image.open(icon_path).convert("RGBA").resize((64, 64))
        return img
    except Exception:
        return Image.new("RGBA", (64, 64), (40, 40, 40, 255))


# ---------------- GUI (Linux: yad/zenity -> Windows: tkinter) ----------------
def _has_cmd(cmd: str) -> bool:
    from shutil import which
    return which(cmd) is not None


def _tk_message(kind: str, title: str, msg: str):
    import tkinter as tk
    import tkinter.messagebox as mb

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        root.lift()
        root.focus_force()
        if kind == "error":
            mb.showerror(title, msg, parent=root)
        else:
            mb.showinfo(title, msg, parent=root)
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _tk_entry(title: str, text: str, label: str, password: bool = False) -> Optional[str]:
    """
    Dialog modal com foco “teimoso”:
    - topmost + lift + focus_force
    - grab_set() para impedir clique fora
    - reforço de foco via after()
    - recuperação em FocusOut (com throttle)
    """
    import tkinter as tk

    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)

    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()

    try:
        root.update_idletasks()
        w, h = 440, 180
        x = (root.winfo_screenwidth() // 2) - (w // 2)
        y = (root.winfo_screenheight() // 2) - (h // 2)
        root.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        pass

    result = {"value": None}
    focus_guard = {"last": 0.0}

    frm = tk.Frame(root, padx=12, pady=12)
    frm.pack(fill="both", expand=True)

    tk.Label(frm, text=text, justify="left").pack(anchor="w")
    tk.Label(frm, text=label).pack(anchor="w", pady=(10, 2))

    entry = tk.Entry(frm, width=48, show="*" if password else "")
    entry.pack(anchor="w", fill="x")

    btns = tk.Frame(frm, pady=12)
    btns.pack(fill="x")

    def ok():
        result["value"] = entry.get()
        root.destroy()

    def cancel():
        result["value"] = None
        root.destroy()

    tk.Button(btns, text="OK", width=10, command=ok).pack(side="right", padx=(6, 0))
    tk.Button(btns, text="Cancelar", width=10, command=cancel).pack(side="right")

    root.bind("<Return>", lambda _: ok())
    root.protocol("WM_DELETE_WINDOW", cancel)

    try:
        root.grab_set()
    except Exception:
        pass

    def force_focus():
        try:
            root.lift()
            root.attributes("-topmost", True)
            root.focus_force()
            entry.focus_set()
            entry.icursor("end")
            root.after(50, lambda: root.attributes("-topmost", False))
            root.after(100, lambda: root.attributes("-topmost", True))
        except Exception:
            pass

    root.after(0, force_focus)
    root.after(200, force_focus)

    def on_focus_out(_evt=None):
        now = time.time()
        if now - focus_guard["last"] < 0.25:
            return
        focus_guard["last"] = now
        root.after(50, force_focus)

    root.bind("<FocusOut>", on_focus_out)

    root.mainloop()
    return result["value"]


def gui_info(msg: str):
    if is_linux() and _has_cmd("yad"):
        subprocess.run(
            ["yad", "--info", "--title=AutoLogin", "--center", "--on-top", "--focus", f"--text={msg}"],
            stderr=subprocess.DEVNULL,
        )
        return
    if is_linux() and _has_cmd("zenity"):
        subprocess.run(
            ["zenity", "--info", "--title=AutoLogin", "--text", msg],
            stderr=subprocess.DEVNULL,
        )
        return
    _tk_message("info", "AutoLogin", msg)


def gui_error(msg: str):
    if is_linux() and _has_cmd("yad"):
        subprocess.run(
            ["yad", "--error", "--title=AutoLogin", "--center", "--on-top", "--focus", f"--text={msg}"],
            stderr=subprocess.DEVNULL,
        )
        return
    if is_linux() and _has_cmd("zenity"):
        subprocess.run(
            ["zenity", "--error", "--title=AutoLogin", "--text", msg],
            stderr=subprocess.DEVNULL,
        )
        return
    _tk_message("error", "AutoLogin", msg)


def gui_entry(title: str, text: str, field_label: str = "Texto") -> Optional[str]:
    if is_linux():
        if _has_cmd("yad"):
            p = subprocess.run(
                [
                    "yad",
                    "--form",
                    "--center",
                    "--on-top",
                    "--focus",
                    f"--title={title}",
                    f"--text={text}",
                    "--separator=",
                    f"--field={field_label}:",
                    "--button=OK:0",
                    "--button=Cancelar:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return None if p.returncode != 0 else p.stdout.strip()

        if _has_cmd("zenity"):
            p = subprocess.run(
                ["zenity", "--entry", f"--title={title}", f"--text={text}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return None if p.returncode != 0 else p.stdout.rstrip("\n")

    return _tk_entry(title, text, label=field_label, password=False)


def gui_password(title: str, text: str, label: str = "Senha") -> Optional[str]:
    if is_linux():
        if _has_cmd("yad"):
            p = subprocess.run(
                [
                    "yad",
                    "--form",
                    "--center",
                    "--on-top",
                    "--focus",
                    f"--title={title}",
                    f"--text={text}",
                    "--separator=",
                    f"--field={label}:H",
                    "--button=OK:0",
                    "--button=Cancelar:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return None if p.returncode != 0 else p.stdout.strip()

        if _has_cmd("zenity"):
            p = subprocess.run(
                ["zenity", "--password", f"--title={title}", f"--text={text}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return None if p.returncode != 0 else p.stdout.rstrip("\n")

    return _tk_entry(title, text, label=label, password=True)


# ---------------- SINGLE INSTANCE (robusto) ----------------
class SingleInstanceGuard:
    """
    Instância única:
    - Windows: Named Mutex (CreateMutexW) + lockfile (msvcrt)
    - Linux: lockfile (fcntl.flock)
    """

    def __init__(self, lock_file: Path, mutex_name: str):
        self.lock_file = lock_file
        self.mutex_name = mutex_name
        self._fh = None
        self._mutex_handle = None

    def acquire_or_exit(self, on_already_running):
        if is_windows():
            if not self._acquire_windows_mutex():
                on_already_running()
                raise SystemExit(0)

        if not self._acquire_file_lock():
            on_already_running()
            raise SystemExit(0)

        atexit.register(self.release)

    def _acquire_windows_mutex(self) -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            CreateMutexW = kernel32.CreateMutexW
            CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
            CreateMutexW.restype = wintypes.HANDLE

            GetLastError = kernel32.GetLastError
            GetLastError.argtypes = ()
            GetLastError.restype = wintypes.DWORD

            ERROR_ALREADY_EXISTS = 183

            handle = CreateMutexW(None, False, self.mutex_name)
            if not handle:
                return True

            last_err = GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
                return False

            self._mutex_handle = handle
            return True

        except Exception as e:
            logging.warning(f"Mutex Windows indisponível (fallback lockfile): {e!r}")
            return True

    def _acquire_file_lock(self) -> bool:
        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.lock_file, "a+b")

            if is_windows():
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            return True

        except (IOError, BlockingIOError, PermissionError):
            return False
        except Exception as e:
            logging.error(f"Falha ao adquirir lockfile: {e!r}")
            return False

    def release(self):
        try:
            if self._fh:
                self._fh.close()
        except Exception:
            pass

        if self._mutex_handle:
            try:
                import ctypes
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._mutex_handle)
            except Exception:
                pass


_singleton = {"guard": None}


def acquire_single_instance_or_exit():
    mutex_name = r"Local\SuricatoAutoLogin.Singleton"
    guard = SingleInstanceGuard(LOCK_FILE, mutex_name)
    guard.acquire_or_exit(
        on_already_running=lambda: gui_info(
            "O Suricato AutoLogin já está rodando!\nVerifique o ícone perto do relógio."
        )
    )
    _singleton["guard"] = guard


def _setup_signal_handlers():
    if is_windows():
        return

    def _handle_sig(_signum, _frame):
        try:
            _stop_event.set()
            lst = _listener_ref.get("listener")
            if lst is not None:
                lst.stop()
        except Exception:
            pass
        try:
            g = _singleton.get("guard")
            if g:
                g.release()
        except Exception:
            pass
        raise SystemExit(0)

    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(s, _handle_sig)
        except Exception:
            pass


# ---------------- CRIPTOGRAFIA E DADOS ----------------
def _derive_key_legacy_sha256(master_password: str) -> bytes:
    digest = hashlib.sha256(master_password.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _derive_key_pbkdf2(master_password: str, salt_b64: str, iterations: int) -> bytes:
    salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
    dk = hashlib.pbkdf2_hmac("sha256", master_password.encode("utf-8"), salt, iterations, dklen=32)
    return base64.urlsafe_b64encode(dk)


def _atomic_write_text(path: Path, content: str, encoding: str = "utf-8"):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding=encoding)
    os.replace(str(tmp), str(path))


def save_credentials(user: str, password: str, master: str):
    try:
        salt = os.urandom(16)
        salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
        iterations = 200_000

        fernet = Fernet(_derive_key_pbkdf2(master, salt_b64, iterations))
        data = {
            "schema_version": 2,
            "kdf": "pbkdf2_sha256",
            "iterations": iterations,
            "salt": salt_b64,
            "usuario": user,
            "senha_enc": fernet.encrypt(password.encode("utf-8")).decode("utf-8"),
            "updated_at": time.time(),
        }

        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(CONFIG_FILE, json.dumps(data, ensure_ascii=False), encoding="utf-8")

        try:
            os.chmod(str(CONFIG_FILE), 0o600)
        except Exception:
            pass

    except Exception as e:
        gui_error(f"Falha ao salvar: {e}")


def load_credentials(master: str) -> Tuple[str, str]:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

        usuario = data.get("usuario")
        senha_enc = data.get("senha_enc")
        if not usuario or not senha_enc:
            raise ValueError("Arquivo de credenciais incompleto.")

        kdf = data.get("kdf")
        if kdf == "pbkdf2_sha256" and data.get("salt") and data.get("iterations"):
            key = _derive_key_pbkdf2(master, data["salt"], int(data["iterations"]))
        else:
            key = _derive_key_legacy_sha256(master)

        fernet = Fernet(key)
        senha = fernet.decrypt(senha_enc.encode("utf-8")).decode("utf-8")
        return usuario, senha

    except (InvalidToken, ValueError):
        raise ValueError("Senha incorreta.")
    except Exception as e:
        logging.error(f"Erro ao carregar credenciais: {e!r}")
        raise ValueError("Falha ao ler credenciais (arquivo inválido/corrompido).")


# ---------------- SETUP ----------------
def perform_login_or_setup() -> Tuple[str, str]:
    if not CONFIG_FILE.exists():
        u = gui_entry("Setup", "Digite o USUÁRIO:", field_label="Usuário")
        if not u:
            sys.exit(0)

        p = gui_password("Setup", "Digite a SENHA:", label="Senha")
        if not p:
            sys.exit(0)

        m1 = gui_password("Segurança", "Crie uma SENHA MESTRA:", label="Senha mestra")
        if not m1:
            sys.exit(0)

        m2 = gui_password("Segurança", "Repita a SENHA MESTRA:", label="Senha mestra (repetir)")
        if not m2:
            sys.exit(0)

        u = u.strip()
        p = p.strip()

        if not u or not p:
            gui_error("Usuário ou senha vazios.")
            sys.exit(1)

        if m1 != m2:
            gui_error("Senhas mestras não coincidem.")
            sys.exit(1)

        save_credentials(u, p, m1)
        gui_info("Configurado! Verifique o ícone na bandeja.")
        return u, p

    attempts = 0
    while attempts < 3:
        m = gui_password("Login", "Senha Mestra:", label="Senha mestra")
        if not m:
            sys.exit(0)
        try:
            return load_credentials(m)
        except ValueError:
            attempts += 1
            gui_error(f"Senha incorreta ({attempts}/3)")
    sys.exit(1)


# ---------------- AUTOMAÇÃO (F12) ----------------
def type_credentials(user: str, password: str):
    try:
        time.sleep(0.10)
        pyautogui.write(user, interval=0.02)
        pyautogui.press("tab")
        pyautogui.write(password, interval=0.02)
        pyautogui.press("enter")
    except pyautogui.FailSafeException:
        logging.warning("FailSafe acionado (mouse no canto superior esquerdo).")
    except Exception as e:
        logging.error(f"Erro ao digitar credenciais: {e!r}")


def start_keyboard_listener(user: str, password: str):
    global _listener

    def on_press(key):
        global _last_trigger_time
        if _stop_event.is_set():
            return False

        if key == keyboard.Key.f12:
            now = time.time()
            if now - _last_trigger_time > COOLDOWN_S:
                _last_trigger_time = now
                threading.Thread(target=type_credentials, args=(user, password), daemon=True).start()

    _listener = keyboard.Listener(on_press=on_press)
    _listener_ref["listener"] = _listener
    _listener.start()


# ---------------- BANDEJA (TRAY) ----------------
def show_about():
    title = "Sobre - Suricato AutoLogin"
    text_plain = (
        f"{APP_NAME}\n"
        f"Versão {__version__}\n"
        f"Autor: {APP_AUTHOR}\n\n"
        "Atalho: F12 (preenche usuário/senha)\n"
    )

    if is_linux():
        if _has_cmd("yad"):
            try:
                iconp = get_icon_path()
                args = [
                    "yad",
                    "--title", title,
                    "--center",
                    "--on-top",
                    "--focus",
                    "--button=OK:0",
                    "--text", text_plain,
                ]
                if iconp:
                    args += ["--image", iconp]
                subprocess.run(args, stderr=subprocess.DEVNULL)
                return
            except Exception as e:
                logging.error(f"Falha ao abrir 'Sobre' via yad: {e!r}")

        if _has_cmd("zenity"):
            try:
                subprocess.run(["zenity", "--info", "--title", title, "--text", text_plain], stderr=subprocess.DEVNULL)
                return
            except Exception as e:
                logging.error(f"Falha ao abrir 'Sobre' via zenity: {e!r}")

    # Fallback Tk (com ícone e layout)
    try:
        import tkinter as tk
        from tkinter import ttk
        from PIL import ImageTk

        root = tk.Tk()
        root.title(title)
        root.attributes("-topmost", True)
        root.resizable(False, False)

        frame = ttk.Frame(root, padding=14)
        frame.pack()

        icon_path = get_icon_path()
        if icon_path and os.path.exists(icon_path):
            img = Image.open(icon_path).convert("RGBA").resize((64, 64))
            photo = ImageTk.PhotoImage(img)
            lbl_img = ttk.Label(frame, image=photo)
            lbl_img.image = photo
            lbl_img.grid(row=0, column=0, rowspan=4, padx=(0, 12), pady=(2, 2))

        ttk.Label(frame, text=APP_NAME, font=("Segoe UI", 12, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(frame, text=f"Versão {__version__}").grid(row=1, column=1, sticky="w", pady=(4, 0))
        ttk.Label(frame, text=f"Autor: {APP_AUTHOR}").grid(row=2, column=1, sticky="w", pady=(4, 0))
        ttk.Label(frame, text="Atalho: F12 (preenche usuário/senha)").grid(row=3, column=1, sticky="w", pady=(10, 0))

        ttk.Separator(frame, orient="horizontal").grid(row=4, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Button(frame, text="OK", command=root.destroy).grid(row=5, column=0, columnspan=2)

        try:
            root.grab_set()
        except Exception:
            pass
        root.lift()
        root.focus_force()

        root.mainloop()
    except Exception as e:
        logging.error(f"Falha ao abrir 'Sobre' (fallback Tkinter): {e!r}")
        gui_info(text_plain)


def run_tray_icon(user: str, password: str):
    def open_about(icon, item):
        threading.Thread(target=show_about, daemon=True).start()

    def open_reset(icon, item):
        def _reset_logic():
            confirmed = False
            if is_linux() and _has_cmd("yad"):
                p = subprocess.run(
                    [
                        "yad",
                        "--question",
                        "--title=Resetar",
                        "--text=Deseja apagar as credenciais e fechar?",
                        "--button=Sim:0",
                        "--button=Não:1",
                        "--center",
                        "--on-top",
                        "--focus",
                    ],
                    stderr=subprocess.DEVNULL,
                )
                confirmed = (p.returncode == 0)
            elif is_linux() and _has_cmd("zenity"):
                p = subprocess.run(
                    ["zenity", "--question", "--title=Resetar", "--text=Deseja apagar as credenciais e fechar?"],
                    stderr=subprocess.DEVNULL,
                )
                confirmed = (p.returncode == 0)
            else:
                try:
                    import tkinter as tk
                    from tkinter import messagebox
                    r = tk.Tk()
                    r.withdraw()
                    r.attributes("-topmost", True)
                    r.lift()
                    r.focus_force()
                    confirmed = messagebox.askyesno("Resetar", "Deseja apagar as credenciais e fechar?", parent=r)
                    r.destroy()
                except Exception:
                    confirmed = False

            if confirmed:
                try:
                    if CONFIG_FILE.exists():
                        os.remove(str(CONFIG_FILE))
                    gui_info("Credenciais apagadas.")
                except Exception as e:
                    logging.error(f"Erro removendo config: {e!r}")
                    gui_error("Não foi possível remover o arquivo de credenciais.")
                on_exit(icon, item)

        threading.Thread(target=_reset_logic, daemon=True).start()

    def on_exit(icon, item):
        _stop_event.set()
        lst = _listener_ref.get("listener")
        try:
            if lst is not None:
                lst.stop()
        except Exception:
            pass
        icon.stop()

    image = load_icon_image()

    menu = pystray.Menu(
        pystray.MenuItem("Status: Ativo", lambda i, it: None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sobre", open_about),
        pystray.MenuItem("Resetar Credenciais", open_reset),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair", on_exit),
    )

    icon = pystray.Icon(APP_SLUG, image, f"{APP_NAME} (F12)", menu)

    try:
        icon.notify("Suricato AutoLogin ativo (F12 para preencher)")
    except Exception:
        pass

    icon.run()


# ---------------- MAIN ----------------
def main():
    _setup_signal_handlers()
    acquire_single_instance_or_exit()

    user, password = perform_login_or_setup()
    start_keyboard_listener(user, password)
    run_tray_icon(user, password)


if __name__ == "__main__":
    main()