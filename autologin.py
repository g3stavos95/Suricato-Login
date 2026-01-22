# autologin.py
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

# Se você quiser usar o ícone externo:
ICON_EXTERNAL_PATH = os.path.expanduser("~/.local/share/icons/autologin.png")

# Nome do ícone embutido no build (PyInstaller --add-data "autologin.png:.")
ICON_EMBED_NAME = "autologin.png"

COOLDOWN_S = 1.5
pyautogui.FAILSAFE = True

_ultimo_disparo = 0.0
running = True
# ==========================================


# ============ RESOURCE PATH (PyInstaller) ==
def resource_path(relative_path: str) -> str:
    """
    Resolve caminho de arquivo tanto em execução normal quanto empacotado (PyInstaller).
    """
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative_path)


def get_icon_path() -> str:
    """
    Prioridade:
      1) ícone externo (~/.local/share/icons/autologin.png)
      2) ícone embutido (autologin.png via PyInstaller)
    """
    if os.path.exists(ICON_EXTERNAL_PATH):
        return ICON_EXTERNAL_PATH

    embedded = resource_path(ICON_EMBED_NAME)
    if os.path.exists(embedded):
        return embedded

    # último fallback: nada
    return ""
# ==========================================


# ============ GUI HELPERS (YAD -> Zenity) ==
def _has_cmd(cmd: str) -> bool:
    from shutil import which
    return which(cmd) is not None


def gui_entry(title: str, text: str, field_label: str = "Texto") -> str | None:
    """Entrada de texto via YAD (fallback Zenity)."""
    if _has_cmd("yad"):
        p = subprocess.run(
            [
                "yad", "--form",
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
        if p.returncode != 0:
            return None
        return p.stdout.strip()

    if _has_cmd("zenity"):
        p = subprocess.run(
            ["zenity", "--entry", f"--title={title}", f"--text={text}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if p.returncode != 0:
            return None
        return p.stdout.rstrip("\n")

    return None


def gui_password(title: str, text: str, label: str = "Senha") -> str | None:
    """
    Senha via YAD com label customizável (ex: 'Senha mestra').
    Fallback para zenity --password (label não customizável).
    """
    if _has_cmd("yad"):
        p = subprocess.run(
            [
                "yad", "--form",
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
        if p.returncode != 0:
            return None
        return p.stdout.strip()

    if _has_cmd("zenity"):
        p = subprocess.run(
            ["zenity", "--password", f"--title={title}", f"--text={text}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if p.returncode != 0:
            return None
        return p.stdout.rstrip("\n")

    return None


def gui_error(msg: str):
    if _has_cmd("yad"):
        subprocess.run(["yad", "--error", "--title=AutoLogin", f"--text={msg}"],
                       stderr=subprocess.DEVNULL)
        return
    if _has_cmd("zenity"):
        subprocess.run(["zenity", "--error", "--title=AutoLogin", f"--text={msg}"],
                       stderr=subprocess.DEVNULL)
        return


def gui_info(msg: str):
    if _has_cmd("yad"):
        subprocess.run(["yad", "--info", "--title=AutoLogin", f"--text={msg}"],
                       stderr=subprocess.DEVNULL)
        return
    if _has_cmd("zenity"):
        subprocess.run(["zenity", "--info", "--title=AutoLogin", f"--text={msg}"],
                       stderr=subprocess.DEVNULL)
        return
# ==========================================


# ============ CRIPTOGRAFIA ================
def derive_key(master_password: str) -> bytes:
    digest = hashlib.sha256(master_password.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def save_credentials(usuario: str, senha: str, master: str):
    fernet = Fernet(derive_key(master))
    data = {
        "usuario": usuario,
        "senha_enc": fernet.encrypt(senha.encode("utf-8")).decode("utf-8"),
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
        senha = fernet.decrypt(data["senha_enc"].encode("utf-8")).decode("utf-8")
    except Exception:
        raise ValueError("Senha mestra incorreta (ou arquivo corrompido).")

    usuario = data.get("usuario")
    if not usuario or not senha:
        raise ValueError("Arquivo de credenciais incompleto.")
    return usuario, senha
# ==========================================


# ============ SETUP (GUI) =================
def first_setup_gui():
    usuario = gui_entry("AutoLogin", "Digite seu usuário:", field_label="Usuário")
    if usuario is None:
        sys.exit(0)

    senha = gui_password("AutoLogin", "Digite sua senha:", label="Senha")
    if senha is None:
        sys.exit(0)

    master1 = gui_password("AutoLogin", "Crie uma senha mestra:", label="Senha mestra")
    if master1 is None:
        sys.exit(0)

    master2 = gui_password("AutoLogin", "Repita a senha mestra:", label="Senha mestra (repetir)")
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

    master = gui_password("AutoLogin", "Digite sua senha mestra:", label="Senha mestra")
    if master is None or not master:
        sys.exit(0)

    try:
        return load_credentials(master)
    except Exception as e:
        gui_error(str(e))
        sys.exit(1)
# ==========================================


# ============ AUTOFILL ====================
def preencher_login(usuario: str, senha: str):
    time.sleep(0.15)
    pyautogui.write(usuario, interval=0.03)
    pyautogui.press("tab")
    pyautogui.write(senha, interval=0.03)
    pyautogui.press("enter")


def keyboard_listener(usuario: str, senha: str):
    global _ultimo_disparo, running

    def on_press(key):
        global _ultimo_disparo
        if not running:
            return False
        if key == keyboard.Key.f12:
            agora = time.time()
            if agora - _ultimo_disparo >= COOLDOWN_S:
                _ultimo_disparo = agora
                try:
                    preencher_login(usuario, senha)
                except Exception:
                    # evita crash silencioso do listener
                    pass

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()
# ==========================================


# ============ TRAY ICON ====================
def load_icon_image() -> Image.Image:
    icon_path = get_icon_path()
    if not icon_path:
        # fallback: cria um ícone simples
        img = Image.new("RGBA", (64, 64), (40, 40, 40, 255))
        return img

    img = Image.open(icon_path).convert("RGBA")
    img = img.resize((64, 64))
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
        pystray.MenuItem("Sair", sair),
    )

    icon = pystray.Icon(
        "AutoLogin",
        load_icon_image(),
        "AutoLogin (F12)",
        menu,
    )

    try:
        icon.notify("Suricato AutoLogin ativo (F12 para preencher)")
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