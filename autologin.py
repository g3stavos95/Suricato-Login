import os
import sys
import json
import time
import threading
import base64
import hashlib
import subprocess

import pyautogui
from pynput import keyboard
from cryptography.fernet import Fernet
import pystray
from PIL import Image

# ================= CONFIG =================
CONFIG_PATH = os.path.expanduser("~/.autologin.txt")
ICON_PATH = os.path.expanduser("~/.local/share/icons/meerkat.png")

COOLDOWN_S = 1.5
pyautogui.FAILSAFE = True

_ultimo_disparo = 0.0
running = True
# ==========================================


# ============ GUI (Zenity + fallback) =====
def _has_zenity() -> bool:
    from shutil import which
    return which("zenity") is not None


def gui_entry(title: str, text: str) -> str | None:
    """Entrada de texto via Zenity. Retorna None se cancelar."""
    if _has_zenity():
        p = subprocess.run(
            ["zenity", "--entry", f"--title={title}", f"--text={text}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if p.returncode != 0:
            return None
        return p.stdout.rstrip("\n")

    # Fallback Tkinter
    import tkinter as tk
    from tkinter import simpledialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    try:
        v = simpledialog.askstring(title, text)
    finally:
        root.destroy()
    return v


def gui_password(title: str, text: str) -> str | None:
    """Senha via Zenity. Retorna None se cancelar."""
    if _has_zenity():
        p = subprocess.run(
            ["zenity", "--password", f"--title={title}", f"--text={text}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if p.returncode != 0:
            return None
        return p.stdout.rstrip("\n")

    # Fallback Tkinter
    import tkinter as tk
    from tkinter import simpledialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    try:
        v = simpledialog.askstring(title, text, show="*")
    finally:
        root.destroy()
    return v


def gui_error(msg: str):
    if _has_zenity():
        subprocess.run(["zenity", "--error", "--title=AutoLogin", f"--text={msg}"],
                       stderr=subprocess.DEVNULL)
        return
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    try:
        messagebox.showerror("AutoLogin", msg)
    finally:
        root.destroy()


def gui_info(msg: str):
    if _has_zenity():
        subprocess.run(["zenity", "--info", "--title=AutoLogin", f"--text={msg}"],
                       stderr=subprocess.DEVNULL)
        return
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    try:
        messagebox.showinfo("AutoLogin", msg)
    finally:
        root.destroy()
# ==========================================


# ============ CRIPTOGRAFIA ================
def derive_key(master_password: str) -> bytes:
    digest = hashlib.sha256(master_password.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def save_credentials(usuario: str, senha: str, master: str):
    fernet = Fernet(derive_key(master))
    data = {
        "usuario": usuario,
        "senha_enc": fernet.encrypt(senha.encode()).decode()
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except Exception:
        pass


def load_credentials(master: str):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    fernet = Fernet(derive_key(master))
    try:
        senha = fernet.decrypt(data["senha_enc"].encode()).decode()
    except Exception:
        raise ValueError("Senha mestra incorreta (ou arquivo corrompido).")

    usuario = data.get("usuario")
    if not usuario or not senha:
        raise ValueError("Arquivo de credenciais incompleto.")
    return usuario, senha
# ==========================================


# ============ SETUP (GUI) =================
def first_setup_gui():
    usuario = gui_entry("AutoLogin", "Usuário:")
    if usuario is None:
        sys.exit(0)

    senha = gui_password("AutoLogin", "Senha:")
    if senha is None:
        sys.exit(0)

    master1 = gui_password("AutoLogin", "Crie uma senha mestra:")
    if master1 is None:
        sys.exit(0)

    master2 = gui_password("AutoLogin", "Repita a senha mestra:")
    if master2 is None:
        sys.exit(0)

    usuario = usuario.strip()
    senha = senha.strip()

    if not usuario or not senha:
        gui_error("Usuário ou senha vazios.")
        sys.exit(1)

    if not master1 or master1 != master2:
        gui_error("Senha mestra não confere.")
        sys.exit(1)

    save_credentials(usuario, senha, master1)
    gui_info("Credenciais salvas com sucesso.")
    return usuario, senha


def load_or_setup():
    if not os.path.exists(CONFIG_PATH):
        return first_setup_gui()

    master = gui_password("AutoLogin", "Senha mestra:")
    if master is None or not master:
        sys.exit(0)

    try:
        return load_credentials(master)
    except Exception as e:
        gui_error(str(e))
        sys.exit(1)
# ==========================================


# ============ AUTOFILL ====================
def preencher_login(usuario, senha):
    time.sleep(0.15)
    pyautogui.write(usuario, interval=0.03)
    pyautogui.press("tab")
    pyautogui.write(senha, interval=0.03)
    pyautogui.press("enter")


def keyboard_listener(usuario, senha):
    global _ultimo_disparo, running

    def on_press(key):
        global _ultimo_disparo
        if not running:
            return False
        if key == keyboard.Key.f12:
            agora = time.time()
            if agora - _ultimo_disparo >= COOLDOWN_S:
                _ultimo_disparo = agora
                preencher_login(usuario, senha)

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()
# ==========================================


# ============ TRAY ICON ====================
def load_icon():
    if not os.path.exists(ICON_PATH):
        gui_error(f"Ícone não encontrado em:\n{ICON_PATH}\n\nAjuste ICON_PATH no script.")
        sys.exit(1)
    img = Image.open(ICON_PATH).convert("RGBA").resize((64, 64))
    return img


def tray_app():
    global running

    def sair(icon, item):
        global running
        running = False
        icon.stop()

    def reset(icon, item):
        try:
            os.remove(CONFIG_PATH)
            icon.notify("Credenciais removidas. Abra o app novamente para configurar.")
        except Exception:
            icon.notify("Não foi possível remover o arquivo de credenciais.")

    menu = pystray.Menu(
        pystray.MenuItem("Resetar credenciais", reset),
        pystray.MenuItem("Sair", sair)
    )

    icon = pystray.Icon(
        "AutoLogin",
        load_icon(),
        "AutoLogin (F12)",
        menu
    )

    # Aviso rápido de “tá rodando”
    try:
        icon.notify("AutoLogin ativo (F12 para preencher)")
    except Exception:
        pass

    icon.run()
# ==========================================


# ============ MAIN =========================
def main():
    usuario, senha = load_or_setup()

    t = threading.Thread(target=keyboard_listener, args=(usuario, senha), daemon=True)
    t.start()

    tray_app()


if __name__ == "__main__":
    main()
