#!/usr/bin/env bash
set -e

APP_NAME="Suricato Login"
DESKTOP_FILE="$HOME/.local/share/applications/autologin.desktop"
ICON_DIR="$HOME/.local/share/icons"
SCRIPT_PATH="$(readlink -f "$0")"

mkdir -p "$(dirname "$DESKTOP_FILE")" "$ICON_DIR"

# 🔐 GARANTIR PERMISSÃO DE EXECUÇÃO (auto)
chmod +x "$SCRIPT_PATH" 2>/dev/null || true

# Verificar zenity
if ! command -v zenity >/dev/null 2>&1; then
  zenity --error \
    --title="AutoLogin" \
    --text="zenity não está instalado.\n\nInstale com:\nsudo apt install zenity" \
    2>/dev/null || true
  exit 1
fi

# Selecionar executável
BIN_PATH="$(zenity --file-selection \
  --title='Selecione o executável autologin (ex: dist/autologin)')"
[ -n "$BIN_PATH" ] || exit 0

# Garantir permissão no executável selecionado
chmod +x "$BIN_PATH" 2>/dev/null || true

# Selecionar ícone
ICON_PATH="$(zenity --file-selection \
  --title='Selecione o ícone (PNG)' \
  --file-filter='PNG | *.png')"
[ -n "$ICON_PATH" ] || exit 0

# Copiar ícone para local padrão
cp -f "$ICON_PATH" "$ICON_DIR/autologin.png"

# Criar .desktop definitivo no menu
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$APP_NAME
Comment=Preenche usuário/senha com F12 (rodando em segundo plano)
Exec=$BIN_PATH
Icon=$ICON_DIR/autologin.png
Terminal=false
Categories=Utility;
StartupNotify=false
EOF

# Permissões do launcher
chmod +x "$DESKTOP_FILE"

# Atualizar cache do menu (se existir)
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

zenity --info \
  --title="AutoLogin" \
  --text="Instalação concluída!\n\nProcure '$APP_NAME' no menu de aplicativos."

# Executar o app imediatamente (opcional)
"$BIN_PATH" >/dev/null 2>&1 &
disown || true
