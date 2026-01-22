#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Suricato AutoLogin (F12)"

APPS_DIR="$HOME/Apps"
BIN_OUT="$APPS_DIR/autologin"

DESKTOP_FILE="$HOME/.local/share/applications/autologin.desktop"
ICON_DIR="$HOME/.local/share/icons"
ICON_OUT="$ICON_DIR/autologin.png"

BUILD_WORKDIR="$(mktemp -d -t autologin_build_XXXXXX)"
LOG_FILE="$BUILD_WORKDIR/setup.log"

cleanup() { rm -rf "$BUILD_WORKDIR" 2>/dev/null || true; }
trap cleanup EXIT

mkdir -p "$APPS_DIR" "$(dirname "$DESKTOP_FILE")" "$ICON_DIR"

# ---- require zenity ----
if ! command -v zenity >/dev/null 2>&1; then
  echo "zenity não instalado. Rode: sudo apt install zenity"
  exit 1
fi

zerr() { zenity --error --title="AutoLogin" --text="$1" 2>/dev/null || true; }
zinfo() { zenity --info --title="AutoLogin" --text="$1" 2>/dev/null || true; }
zquestion() { zenity --question --title="AutoLogin" --text="$1" 2>/dev/null; }

# Desktop dir (funciona em pt/en)
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
DESKTOP_SHORTCUT="$DESKTOP_DIR/Suricato AutoLogin.desktop"

# ---- select inputs ----
PY_PATH="$(zenity --file-selection --title='Selecione o autologin.py' --file-filter='Python | *.py')"
[ -n "${PY_PATH:-}" ] || exit 0

ICON_PATH="$(zenity --file-selection --title='Selecione o ícone (PNG)' --file-filter='PNG | *.png')"
[ -n "${ICON_PATH:-}" ] || exit 0

if [ ! -f "$PY_PATH" ]; then zerr "Arquivo não encontrado:\n$PY_PATH"; exit 1; fi
if [ ! -f "$ICON_PATH" ]; then zerr "Ícone não encontrado:\n$ICON_PATH"; exit 1; fi

if ! command -v python3 >/dev/null 2>&1; then
  zerr "python3 não encontrado no sistema."
  exit 1
fi

# Dependências
REQ_PKGS=(pyautogui pynput cryptography pystray pillow pyinstaller)

# Função para rodar comando e logar
run_step() {
  local cmd="$1"
  echo ">>> $cmd" >> "$LOG_FILE"
  bash -lc "$cmd" >> "$LOG_FILE" 2>&1
}

# ---- Progress UI ----
(
  echo "5";  echo "# Preparando ambiente..."
  run_step "python3 -m pip install --user --upgrade pip"

  echo "20"; echo "# Instalando/atualizando dependências Python..."
  run_step "python3 -m pip install --user --upgrade ${REQ_PKGS[*]}"

  echo "45"; echo "# Preparando arquivos para build..."
  cp -f "$PY_PATH" "$BUILD_WORKDIR/autologin.py"
  cp -f "$ICON_PATH" "$BUILD_WORKDIR/autologin.png"

  echo "65"; echo "# Buildando executável (PyInstaller)..."
  cd "$BUILD_WORKDIR"
  rm -rf build dist autologin.spec 2>/dev/null || true
  run_step "python3 -m PyInstaller --onefile --noconsole --clean --name autologin --add-data \"$BUILD_WORKDIR/autologin.png:.\" \"$BUILD_WORKDIR/autologin.py\""

  echo "85"; echo "# Instalando executável e ícone..."
  if [ ! -f "$BUILD_WORKDIR/dist/autologin" ]; then
    echo "Build terminou, mas não encontrei $BUILD_WORKDIR/dist/autologin" >> "$LOG_FILE"
    exit 2
  fi

  cp -f "$BUILD_WORKDIR/dist/autologin" "$BIN_OUT"
  chmod +x "$BIN_OUT" 2>/dev/null || true
  cp -f "$BUILD_WORKDIR/autologin.png" "$ICON_OUT"

  echo "93"; echo "# Criando launcher no menu..."
  cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$APP_NAME
Comment=Preenche usuário/senha com F12 (rodando em segundo plano)
Exec=$BIN_OUT
Icon=$ICON_OUT
Terminal=false
Categories=Utility;
StartupNotify=false
EOF
  chmod +x "$DESKTOP_FILE" 2>/dev/null || true
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

  echo "97"; echo "# Criando atalho na Área de Trabalho..."
  mkdir -p "$DESKTOP_DIR"
  cp -f "$DESKTOP_FILE" "$DESKTOP_SHORTCUT"
  chmod +x "$DESKTOP_SHORTCUT" 2>/dev/null || true
  gio set "$DESKTOP_SHORTCUT" metadata::trusted true 2>/dev/null || true

  echo "100"; echo "# Concluído!"
) | zenity --progress \
    --title="AutoLogin - Instalação/Atualização" \
    --text="Iniciando..." \
    --percentage=0 \
    --auto-close \
    --no-cancel \
    2>/dev/null

# Validação final
if [ ! -x "$BIN_OUT" ]; then
  zerr "Falha na instalação/build.\n\nLog salvo em:\n$LOG_FILE"
  if zquestion "Deseja abrir o log agora?"; then
    xdg-open "$LOG_FILE" >/dev/null 2>&1 || true
  fi
  exit 1
fi

zinfo "Instalação concluída!\n\nExecutável:\n$BIN_OUT\n\nNo menu:\n$APP_NAME\n\nAtalho criado em:\n$DESKTOP_SHORTCUT"

if zquestion "Deseja iniciar agora?"; then
  "$BIN_OUT" >/dev/null 2>&1 &
  disown || true
fi

exit 0