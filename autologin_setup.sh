#!/usr/bin/env bash
# autologin_setup.sh
set -euo pipefail

APP_NAME="Suricato AutoLogin (F12)"

APPS_DIR="$HOME/Apps"
BIN_OUT="$APPS_DIR/autologin"

DESKTOP_FILE="$HOME/.local/share/applications/autologin.desktop"
ICON_DIR="$HOME/.local/share/icons"
ICON_OUT="$ICON_DIR/autologin.png"

CACHE_DIR="$HOME/.cache/autologin"
LOG_FILE="$CACHE_DIR/setup.log"

BUILD_WORKDIR="$(mktemp -d -t autologin_build_XXXXXX)"
cleanup() { rm -rf "$BUILD_WORKDIR" 2>/dev/null || true; }
trap cleanup EXIT

mkdir -p "$CACHE_DIR"
: > "$LOG_FILE"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE" >/dev/null; }

has_yad() { command -v yad >/dev/null 2>&1; }
has_zenity() { command -v zenity >/dev/null 2>&1; }
has_gui() { has_yad || has_zenity; }

# -------- CLI progress (when no GUI) --------
cli_progress() {
  local percent="$1"
  local msg="${2:-}"
  local blocks=$((percent/2))
  local bar
  bar="$(printf "%0.s#" $(seq 1 "$blocks" 2>/dev/null || true))"
  printf "\r[%-50s] %3s%%  %s" "$bar" "$percent" "$msg"
}

progress_pipe() {
  if has_yad; then
    yad --progress \
      --title="AutoLogin - Instalação/Atualização" \
      --text="Iniciando..." \
      --percentage=0 \
      --auto-close \
      --no-cancel \
      2>/dev/null
  elif has_zenity; then
    zenity --progress \
      --title="AutoLogin - Instalação/Atualização" \
      --text="Iniciando..." \
      --percentage=0 \
      --auto-close \
      --no-cancel \
      2>/dev/null
  else
    local msg=""
    while IFS= read -r line; do
      if [[ "$line" == \#* ]]; then
        msg="${line#\# }"
      else
        cli_progress "$line" "$msg"
      fi
    done
    echo
  fi
}

# -------- UI wrappers --------
ui_error() {
  local msg="$1"
  log "ERROR: $msg"
  if has_yad; then
    yad --error --title="AutoLogin" --text="$msg\n\nLog: $LOG_FILE" 2>/dev/null || true
  elif has_zenity; then
    zenity --error --title="AutoLogin" --text="$msg\n\nLog: $LOG_FILE" 2>/dev/null || true
  else
    echo "ERRO: $msg"
    echo "Log: $LOG_FILE"
  fi
}

ui_info() {
  local msg="$1"
  log "INFO: $msg"
  if has_yad; then
    yad --info --title="AutoLogin" --text="$msg" 2>/dev/null || true
  elif has_zenity; then
    zenity --info --title="AutoLogin" --text="$msg" 2>/dev/null || true
  else
    echo "$msg"
  fi
}

ui_question() {
  local msg="$1"
  log "QUESTION: $msg"
  if has_yad; then
    yad --question --title="AutoLogin" --text="$msg" 2>/dev/null
  elif has_zenity; then
    zenity --question --title="AutoLogin" --text="$msg" 2>/dev/null
  else
    read -r -p "$msg (s/N): " ans
    [[ "${ans:-}" =~ ^[sS]$ ]]
  fi
}

pick_file() {
  local title="$1"
  local filter="$2"
  if has_yad; then
    yad --file --title="$title" 2>/dev/null || true
  elif has_zenity; then
    zenity --file-selection --title="$title" --file-filter="$filter" 2>/dev/null || true
  else
    echo ""
  fi
}

# -------- apt installer (best effort) --------
apt_install_if_missing() {
  local pkg="$1"

  if command -v dpkg >/dev/null 2>&1 && dpkg -s "$pkg" >/dev/null 2>&1; then
    log "APT: $pkg já instalado."
    return 0
  fi

  log "APT: tentando instalar $pkg ..."
  if command -v sudo >/dev/null 2>&1; then
    sudo apt-get update -y >>"$LOG_FILE" 2>&1 || true
    sudo apt-get install -y "$pkg" >>"$LOG_FILE" 2>&1 || true
  else
    apt-get update -y >>"$LOG_FILE" 2>&1 || true
    apt-get install -y "$pkg" >>"$LOG_FILE" 2>&1 || true
  fi

  command -v dpkg >/dev/null 2>&1 && dpkg -s "$pkg" >/dev/null 2>&1
}

run_step() {
  local cmd="$1"
  log "RUN: $cmd"
  bash -lc "$cmd" >>"$LOG_FILE" 2>&1
}

# -------- pre-req checks --------
if ! command -v python3 >/dev/null 2>&1; then
  ui_error "python3 não encontrado. Instale com: sudo apt install python3"
  exit 1
fi

mkdir -p "$APPS_DIR" "$(dirname "$DESKTOP_FILE")" "$ICON_DIR"

# ---- FASE 1: preparar instalador (com progresso) ----
(
  echo "5";  echo "# Preparando instalador..."
  echo "10"; echo "# Verificando pip..."
  if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "15"; echo "# Instalando python3-pip (APT)..."
    apt_install_if_missing python3-pip || true
  fi

  echo "25"; echo "# Verificando GUI (yad/zenity)..."
  if ! has_yad; then
    echo "30"; echo "# Instalando yad (APT)..."
    apt_install_if_missing yad || true
  fi
  if ! has_gui; then
    echo "35"; echo "# Instalando zenity (APT) como fallback..."
    apt_install_if_missing zenity || true
  fi

  echo "45"; echo "# Verificando dependências extras (APT)..."
  apt_install_if_missing python3-tk || true
  apt_install_if_missing scrot || true

  echo "60"; echo "# Atualizando pip..."
  run_step "python3 -m pip install --user --upgrade pip"

  echo "100"; echo "# Instalador pronto!"
) | progress_pipe

# revalida pip
if ! python3 -m pip --version >/dev/null 2>&1; then
  ui_error "pip não encontrado para python3. Instale com: sudo apt install python3-pip"
  exit 1
fi

# revalida GUI (precisamos para seleção de arquivo)
if ! has_gui; then
  ui_error "Nenhuma GUI disponível (yad/zenity).\nInstale com: sudo apt install yad"
  exit 1
fi

# ---- Seleção de arquivos (GUI) ----
PY_PATH="$(pick_file "Selecione o autologin.py" "Python | *.py")"
[ -n "${PY_PATH:-}" ] || exit 0
ICON_PATH="$(pick_file "Selecione o ícone (PNG)" "PNG | *.png")"
[ -n "${ICON_PATH:-}" ] || exit 0

if [ ! -f "$PY_PATH" ]; then ui_error "Arquivo não encontrado: $PY_PATH"; exit 1; fi
if [ ! -f "$ICON_PATH" ]; then ui_error "Ícone não encontrado: $ICON_PATH"; exit 1; fi

REQ_PKGS=(pyautogui pynput cryptography pystray pillow pyinstaller)

# ---- FASE 2: deps python + build + instalar atalhos ----
(
  echo "5";  echo "# Instalando dependências Python..."
  run_step "python3 -m pip install --user --upgrade ${REQ_PKGS[*]}"

  echo "30"; echo "# Preparando arquivos para build..."
  cp -f "$PY_PATH" "$BUILD_WORKDIR/autologin.py"
  cp -f "$ICON_PATH" "$BUILD_WORKDIR/autologin.png"

  echo "55"; echo "# Buildando executável (PyInstaller)..."
  cd "$BUILD_WORKDIR"
  rm -rf build dist autologin.spec 2>/dev/null || true
  run_step "python3 -m PyInstaller --onefile --noconsole --clean \
    --name autologin \
    --add-data \"$BUILD_WORKDIR/autologin.png:.\" \
    \"$BUILD_WORKDIR/autologin.py\""

  echo "75"; echo "# Instalando executável e ícone..."
  if [ ! -f "$BUILD_WORKDIR/dist/autologin" ]; then
    log "ERRO: build terminou mas não encontrei $BUILD_WORKDIR/dist/autologin"
    exit 2
  fi

  cp -f "$BUILD_WORKDIR/dist/autologin" "$BIN_OUT"
  chmod +x "$BIN_OUT" 2>/dev/null || true

  # instala o ícone externo para o .desktop e também para fallback do app
  cp -f "$BUILD_WORKDIR/autologin.png" "$ICON_OUT"

  echo "90"; echo "# Criando atalhos..."
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
  update-desktop-database "$HOME/.local/share/applications" >>"$LOG_FILE" 2>&1 || true

  DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
  DESKTOP_SHORTCUT="$DESKTOP_DIR/Suricato AutoLogin.desktop"
  mkdir -p "$DESKTOP_DIR"
  cp -f "$DESKTOP_FILE" "$DESKTOP_SHORTCUT"
  chmod +x "$DESKTOP_SHORTCUT" 2>/dev/null || true
  gio set "$DESKTOP_SHORTCUT" metadata::trusted true >>"$LOG_FILE" 2>&1 || true

  echo "100"; echo "# Concluído!"
) | progress_pipe

# ---- Final validation ----
if [ ! -x "$BIN_OUT" ]; then
  ui_error "Falha na instalação/build.\nVeja o log em:\n$LOG_FILE"
  if ui_question "Deseja abrir o log agora?"; then
    xdg-open "$LOG_FILE" >/dev/null 2>&1 || true
  fi
  exit 1
fi

ui_info "Instalação concluída!\n\nExecutável:\n$BIN_OUT\n\nNo menu:\n$APP_NAME\n\nLog:\n$LOG_FILE"

if ui_question "Deseja iniciar agora?"; then
  "$BIN_OUT" >/dev/null 2>&1 &
  disown || true
fi

exit 0