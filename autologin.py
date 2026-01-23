# autologin.py
# ======================================================================================
# Suricato AutoLogin (F12)
# Versão: 1.0
# ======================================================================================
# IMPORTANTE (promessa de compatibilidade):
#   - Este arquivo foi APENAS DOCUMENTADO para facilitar manutenção.
#   - A lógica/fluxo do código original foi preservada (sem mudanças funcionais intencionais).
#
# O que este app faz:
#   - Roda em background com ícone na bandeja (tray icon).
#   - Ao pressionar F12, preenche usuário/senha na janela atualmente focada:
#       usuário -> TAB -> senha -> ENTER
#   - Credenciais ficam em JSON e a senha fica criptografada (Fernet).
#   - Há um "setup inicial" via GUI:
#       Linux: tenta YAD, se não tiver tenta Zenity
#       Windows: Tkinter
#
# Pontos de atenção:
#   - pyautogui.FAILSAFE=True: mover o mouse pro canto superior esquerdo interrompe o pyautogui.
#   - A "senha mestra" atualmente é derivada com SHA256 direto (sem salt/KDF). Funciona,
#     mas pode ser reforçado depois (PBKDF2/Argon2) sem mudar UX.
#   - O listener global de teclado (pynput) é encerrado ao clicar “Sair” no tray.
#
# Paths:
#   - Windows:
#       Config:  %APPDATA%\SuricatoAutoLogin\autologin.json
#       Icon:    %APPDATA%\SuricatoAutoLogin\autologin.png  (externo)
#       Log:     %APPDATA%\SuricatoAutoLogin\autologin.log
#   - Linux:
#       Config:  ~/.autologin.json
#       Icon:    ~/.local/share/icons/autologin.png (externo)
#       Log:     ~/.cache/autologin/autologin.log
#
# Build (PyInstaller):
#   - O setup empacota autologin.png via --add-data "autologin.png;."
#   - Em runtime, este app procura primeiro o ícone externo; se não existir,
#     tenta usar o ícone embutido (PyInstaller _MEIPASS).
# ======================================================================================

import os
import sys
import json
import time
import threading
import base64
import hashlib
import subprocess
import platform
from pathlib import Path

import pyautogui
from pynput import keyboard
from cryptography.fernet import Fernet
import pystray
from PIL import Image

# ---------------- VERSION ----------------
__version__ = "1.0"
# ----------------------------------------


# ---------------- CONFIG (constantes do app) ----------------
# Nome amigável e "slug" (usado em paths no Windows)
APP_NAME = "Suricato AutoLogin"
APP_SLUG = "SuricatoAutoLogin"

# Cooldown para impedir múltiplos disparos em sequência (ex.: tecla repetindo)
COOLDOWN_S = 1.5

# Segurança do pyautogui:
# Se o mouse for movido para o canto superior esquerdo, pyautogui aborta ações.
pyautogui.FAILSAFE = True

# Controle do último disparo do F12 (para aplicar cooldown)
_ultimo_disparo = 0.0

# Usamos Event para encerramento limpo (threads consultam esse estado)
stop_event = threading.Event()

# Referência global do listener (para parar imediatamente no menu “Sair”)
_listener_ref = {"listener": None}
# -----------------------------------------------------------


# ---------------- LOG (debug/forense) ----------------
def get_log_path() -> Path:
    """Define o caminho do log conforme o sistema operacional.

    Windows:
      %APPDATA%\SuricatoAutoLogin\autologin.log

    Linux:
      ~/.cache/autologin/autologin.log
    """
    if platform.system().lower().startswith("win"):
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(appdata) / APP_SLUG
    else:
        base = Path.home() / ".cache" / "autologin"
    base.mkdir(parents=True, exist_ok=True)
    return base / "autologin.log"


LOG_PATH = get_log_path()


def log(msg: str):
    """Log simples em arquivo (append).

    Observação:
      - Mantém o arquivo de log como texto UTF-8.
      - Qualquer falha de IO é silenciosa (não interrompe o app).
    """
    try:
        LOG_PATH.write_text(
            (LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else "")
            + f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n",
            encoding="utf-8",
        )
    except Exception:
        pass
# -----------------------------------------------------


# ---------------- OS DETECTION ----------------
def get_os() -> str:
    """Retorna uma string simplificada do sistema operacional."""
    s = platform.system().lower()
    if "windows" in s:
        return "windows"
    if "linux" in s:
        return "linux"
    if "darwin" in s or "mac" in s:
        return "mac"
    return "other"


def is_windows() -> bool:
    """Atalho para checagem do OS."""
    return get_os() == "windows"


def is_linux() -> bool:
    """Atalho para checagem do OS."""
    return get_os() == "linux"
# ---------------------------------------------


# ---------------- PATHS (cross-platform) ----------------
def get_config_path() -> Path:
    """Retorna o caminho do arquivo de configuração/credenciais.

    Linux:
      ~/.autologin.json

    Windows:
      %APPDATA%\SuricatoAutoLogin\autologin.json
    """
    if is_windows():
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(appdata) / APP_SLUG
        base.mkdir(parents=True, exist_ok=True)
        return base / "autologin.json"
    else:
        return Path.home() / ".autologin.json"


def get_external_icon_path() -> Path:
    """Retorna o caminho do ícone externo (fora do executável).

    Linux:
      ~/.local/share/icons/autologin.png

    Windows:
      %APPDATA%\SuricatoAutoLogin\autologin.png
    """
    if is_windows():
        cfg_dir = get_config_path().parent
        return cfg_dir / "autologin.png"
    else:
        return Path.home() / ".local" / "share" / "icons" / "autologin.png"


CONFIG_PATH = get_config_path()
ICON_EXTERNAL_PATH = get_external_icon_path()

# Nome do ícone embutido no build (PyInstaller --add-data "autologin.png;.")
ICON_EMBED_NAME = "autologin.png"
# --------------------------------------------------------


# ---------------- RESOURCE PATH (PyInstaller) ----------------
def resource_path(relative_path: str) -> str:
    """Resolve caminho de arquivo tanto em execução normal quanto empacotado (PyInstaller).

    PyInstaller:
      - disponibiliza sys._MEIPASS como base temporária para recursos empacotados.
    """
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative_path)


def get_icon_path() -> str:
    """Escolhe o melhor ícone disponível.

    Prioridade:
      1) ícone externo (por OS)
      2) ícone embutido no executável (autologin.png via PyInstaller)
      3) vazio -> caller decide um fallback (imagem cinza)
    """
    if ICON_EXTERNAL_PATH.exists():
        return str(ICON_EXTERNAL_PATH)

    embedded = resource_path(ICON_EMBED_NAME)
    if os.path.exists(embedded):
        return embedded

    return ""
# --------------------------------------------------------------


# ---------------- GUI HELPERS ----------------
def _has_cmd(cmd: str) -> bool:
    """Checa se um comando existe no PATH (Linux)."""
    from shutil import which
    return which(cmd) is not None


def _tk_init():
    """Inicializa Tk em modo 'sem janela principal' e sempre no topo (Windows)."""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def _tk_message(kind: str, title: str, msg: str):
    """Mostra MessageBox via Tkinter."""
    import tkinter.messagebox as mb
    root = _tk_init()
    try:
        if kind == "error":
            mb.showerror(title, msg, parent=root)
        else:
            mb.showinfo(title, msg, parent=root)
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _tk_entry(title: str, text: str, label: str = "Texto", password: bool = False) -> str | None:
    """Janela de input via Tkinter (Windows), com suporte a campo de senha."""
    import tkinter as tk

    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(False, False)

    val = {"result": None}

    frm = tk.Frame(root, padx=12, pady=12)
    frm.pack()

    tk.Label(frm, text=text, justify="left").pack(anchor="w")
    tk.Label(frm, text=label).pack(anchor="w", pady=(10, 2))

    entry = tk.Entry(frm, width=40, show="*" if password else "")
    entry.pack(anchor="w")
    entry.focus_set()

    btns = tk.Frame(frm, pady=12)
    btns.pack(fill="x")

    def ok():
        val["result"] = entry.get()
        root.destroy()

    def cancel():
        val["result"] = None
        root.destroy()

    tk.Button(btns, text="OK", width=10, command=ok).pack(side="right", padx=(6, 0))
    tk.Button(btns, text="Cancelar", width=10, command=cancel).pack(side="right")

    root.bind("<Return>", lambda _: ok())
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()
    return val["result"]


def gui_entry(title: str, text: str, field_label: str = "Texto") -> str | None:
    """Entrada de texto (usuário).

    Linux:
      tenta YAD -> Zenity

    Windows:
      Tkinter
    """
    if is_linux():
        if _has_cmd("yad"):
            p = subprocess.run(
                ["yad", "--form", f"--title={title}", f"--text={text}",
                 "--separator=", f"--field={field_label}:", "--button=OK:0", "--button=Cancelar:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            return None if p.returncode != 0 else p.stdout.strip()

        if _has_cmd("zenity"):
            p = subprocess.run(
                ["zenity", "--entry", f"--title={title}", f"--text={text}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            return None if p.returncode != 0 else p.stdout.rstrip("\n")

    return _tk_entry(title, text, label=field_label, password=False)


def gui_password(title: str, text: str, label: str = "Senha") -> str | None:
    """Entrada de senha (campo mascarado).

    Linux:
      - YAD: permite label custom (e campo hidden via :H)
      - Zenity: label não custom (usa título/texto)

    Windows:
      Tkinter (label custom)
    """
    if is_linux():
        if _has_cmd("yad"):
            p = subprocess.run(
                ["yad", "--form", f"--title={title}", f"--text={text}",
                 "--separator=", f"--field={label}:H", "--button=OK:0", "--button=Cancelar:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            return None if p.returncode != 0 else p.stdout.strip()

        if _has_cmd("zenity"):
            p = subprocess.run(
                ["zenity", "--password", f"--title={title}", f"--text={text}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            return None if p.returncode != 0 else p.stdout.rstrip("\n")

    return _tk_entry(title, text, label=label, password=True)


def gui_error(msg: str):
    """Mensagem de erro cross-platform."""
    if is_linux() and _has_cmd("yad"):
        subprocess.run(["yad", "--error", "--title=AutoLogin", f"--text={msg}"], stderr=subprocess.DEVNULL)
        return
    if is_linux() and _has_cmd("zenity"):
        subprocess.run(["zenity", "--error", "--title=AutoLogin", f"--text={msg}"], stderr=subprocess.DEVNULL)
        return
    _tk_message("error", "AutoLogin", msg)


def gui_info(msg: str):
    """Mensagem informativa cross-platform."""
    if is_linux() and _has_cmd("yad"):
        subprocess.run(["yad", "--info", "--title=AutoLogin", f"--text={msg}"], stderr=subprocess.DEVNULL)
        return
    if is_linux() and _has_cmd("zenity"):
        subprocess.run(["zenity", "--info", "--title=AutoLogin", f"--text={msg}"], stderr=subprocess.DEVNULL)
        return
    _tk_message("info", "AutoLogin", msg)
# --------------------------------------------------


# ---------------- CRIPTOGRAFIA ----------------
def derive_key(master_password: str) -> bytes:
    """Deriva uma chave Fernet a partir da senha mestra.

    Nota:
      - SHA256 direto (sem salt/KDF) foi mantido para preservar a compatibilidade v1.0.
      - Melhoria futura (sem mudar UX): PBKDF2/Argon2 + salt salvo no config.
    """
    digest = hashlib.sha256(master_password.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def save_credentials(usuario: str, senha: str, master: str):
    """Salva o usuário e senha criptografada em JSON no CONFIG_PATH."""
    fernet = Fernet(derive_key(master))
    data = {
        "usuario": usuario,
        "senha_enc": fernet.encrypt(senha.encode("utf-8")).decode("utf-8"),
    }

    cfg_path = CONFIG_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(data), encoding="utf-8")

    # No Linux, ajuda a restringir permissões. No Windows, chmod não tem efeito real.
    try:
        os.chmod(str(cfg_path), 0o600)
    except Exception:
        pass


def load_credentials(master: str):
    """Carrega credenciais do JSON e descriptografa a senha usando a senha mestra."""
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    fernet = Fernet(derive_key(master))
    try:
        senha = fernet.decrypt(data["senha_enc"].encode("utf-8")).decode("utf-8")
    except Exception:
        raise ValueError("Senha mestra incorreta (ou arquivo corrompido).")

    usuario = data.get("usuario")
    if not usuario or not senha:
        raise ValueError("Arquivo de credenciais incompleto.")
    return usuario, senha
# ---------------------------------------------


# ---------------- SETUP (GUI) ----------------
def first_setup_gui():
    """Fluxo de primeiro uso: coleta usuário/senha e cria senha mestra."""
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
    """Carrega credenciais existentes ou executa o setup inicial se não existir config."""
    if not CONFIG_PATH.exists():
        return first_setup_gui()

    master = gui_password("AutoLogin", "Digite sua senha mestra:", label="Senha mestra")
    if master is None or not master:
        sys.exit(0)

    try:
        return load_credentials(master)
    except Exception as e:
        gui_error(str(e))
        sys.exit(1)
# ---------------------------------------------


# ---------------- AUTOFILL ----------------
def preencher_login(usuario: str, senha: str):
    """Executa o preenchimento via pyautogui na janela em foco."""
    # Pequeno delay para o usuário focar no campo correto
    time.sleep(0.15)
    pyautogui.write(usuario, interval=0.03)
    pyautogui.press("tab")
    pyautogui.write(senha, interval=0.03)
    pyautogui.press("enter")


def keyboard_listener(usuario: str, senha: str):
    """Listener global de teclado (pynput).

    Responsabilidades:
      - Capturar F12
      - Aplicar cooldown (COOLDOWN_S) para evitar duplicidade
      - Encerrar limpo quando stop_event for setado
    """
    global _ultimo_disparo

    def on_press(key):
        global _ultimo_disparo

        # Se solicitar parada, encerramos o listener (retornando False).
        if stop_event.is_set():
            return False

        # Hotkey
        if key == keyboard.Key.f12:
            agora = time.time()
            if agora - _ultimo_disparo >= COOLDOWN_S:
                _ultimo_disparo = agora
                try:
                    preencher_login(usuario, senha)
                except Exception as e:
                    log(f"Erro ao preencher_login: {e!r}")

    listener = keyboard.Listener(on_press=on_press)
    _listener_ref["listener"] = listener
    listener.start()
    listener.join()
# -----------------------------------------


# ---------------- TRAY ICON ----------------
def load_icon_image() -> Image.Image:
    """Carrega o ícone (externo -> embutido -> fallback cinza)."""
    icon_path = get_icon_path()
    if not icon_path:
        return Image.new("RGBA", (64, 64), (40, 40, 40, 255))

    img = Image.open(icon_path).convert("RGBA")
    img = img.resize((64, 64))
    return img


# ---------------- ABOUT (menu "Sobre") ----------------
def show_about():
    """Exibe a janela 'Sobre' com ícone e versão do aplicativo.

    Objetivo:
      - Disponibilizar no tray um menu 'Sobre' com informações básicas do app.
      - Mostrar o ícone e a versão (__version__) para facilitar suporte/manutenção.

    Implementação por OS:
      - Linux: tenta YAD (com imagem) -> Zenity (sem imagem)
      - Windows: Tkinter (com imagem, usando ImageTk)
      - Fallback: se algo falhar, registra no log e não derruba o app
    """

    title = "Sobre - Suricato AutoLogin"
    text = f"{APP_NAME}\nVersão {__version__}\n\nAutoLogin via tecla F12"

    # Linux: preferimos YAD (aceita imagem); se não houver, usamos Zenity.
    if is_linux():
        if _has_cmd("yad"):
            try:
                subprocess.run(
                    [
                        "yad",
                        "--title", title,
                        "--text", text,
                        "--image", get_icon_path(),
                        "--button=OK:0",
                    ],
                    stderr=subprocess.DEVNULL,
                )
                return
            except Exception as e:
                log(f"Falha ao abrir 'Sobre' via yad: {e!r}")

        if _has_cmd("zenity"):
            try:
                subprocess.run(
                    ["zenity", "--info", "--title", title, "--text", text],
                    stderr=subprocess.DEVNULL,
                )
                return
            except Exception as e:
                log(f"Falha ao abrir 'Sobre' via zenity: {e!r}")

    # Windows (e fallback geral): Tkinter com imagem (se disponível)
    try:
        import tkinter as tk
        from tkinter import ttk
        from PIL import ImageTk

        root = tk.Tk()
        root.title(title)
        root.attributes("-topmost", True)
        root.resizable(False, False)

        frame = ttk.Frame(root, padding=12)
        frame.pack()

        # Carrega ícone (externo/embutido) e mostra na janela.
        icon_path = get_icon_path()
        if icon_path and os.path.exists(icon_path):
            img = Image.open(icon_path).convert("RGBA").resize((64, 64))
            photo = ImageTk.PhotoImage(img)
            lbl_img = ttk.Label(frame, image=photo)
            lbl_img.image = photo  # evita garbage collection
            lbl_img.pack(pady=(0, 8))

        ttk.Label(frame, text=APP_NAME, font=("Segoe UI", 11, "bold")).pack()
        ttk.Label(frame, text=f"Versão {__version__}").pack(pady=(4, 0))
        ttk.Label(frame, text="AutoLogin via tecla F12").pack(pady=(6, 10))
        ttk.Button(frame, text="OK", command=root.destroy).pack()

        root.mainloop()
    except Exception as e:
        # Não derruba o app em caso de erro de GUI
        log(f"Falha ao abrir 'Sobre' (fallback Tkinter): {e!r}")
# ------------------------------------------------------



def tray_app():
    """Inicializa o ícone na bandeja e o menu (Resetar / Sair).

    Observação importante:
      - Ao clicar “Sair”, paramos o listener imediatamente chamando listener.stop().
        Isso evita esperar a próxima tecla para encerrar.
    """

    def sair(icon, item):
        stop_event.set()

        # Para o listener imediatamente (não espera próxima tecla)
        lst = _listener_ref.get("listener")
        try:
            if lst is not None:
                lst.stop()
        except Exception:
            pass

        icon.stop()

    def reset(icon, item):
        try:
            os.remove(str(CONFIG_PATH))
            icon.notify("Credenciais removidas. Abra o app novamente para configurar.")
        except Exception:
            icon.notify("Não foi possível remover o arquivo de credenciais.")

    menu = pystray.Menu(
        pystray.MenuItem("Sobre", lambda icon, item: show_about()),
        pystray.MenuItem("Resetar credenciais", reset),
        pystray.MenuItem("Sair", sair),
    )

    icon = pystray.Icon(
        "AutoLogin",
        load_icon_image(),
        "AutoLogin (F12)",
        menu,
    )

    # Alguns ambientes não suportam notify -> ignoramos falhas
    try:
        icon.notify("Suricato AutoLogin ativo (F12 para preencher)")
    except Exception:
        pass

    icon.run()
# ------------------------------------------


def main():
    """Ponto de entrada principal.

    Fluxo:
      1) load_or_setup() -> garante credenciais (setup inicial ou leitura do arquivo)
      2) inicia listener de teclado em thread daemon
      3) inicia tray_app() (loop principal do ícone)
    """
    usuario, senha = load_or_setup()

    # Thread do listener em daemon para não travar o encerramento em caso de erro
    t = threading.Thread(target=keyboard_listener, args=(usuario, senha), daemon=True)
    t.start()

    tray_app()


if __name__ == "__main__":
    main()
