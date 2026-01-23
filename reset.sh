#!/usr/bin/env bash
# ======================================================================================
# reset.sh — Documentação (v1.1)
# Autor: Gustavo Pires
# Data: 2026-01-23
# Suricato AutoLogin (F12) - RESET (Linux)
# Versão: 1.1
# Objetivo: Limpar configurações, ícones e binários do sistema.
# ======================================================================================

# Fail-fast: encerra ao primeiro erro de comando (exceto onde há '|| true').
set -e

# Identificador usado para compor caminhos/pastas relacionados ao app.
APP_SLUG="suricato_autologin"
CONFIG_DIR="$HOME/.config/$APP_SLUG"
BIN_PATH="$HOME/Apps/autologin"
DESKTOP_FILE="$HOME/.local/share/applications/autologin.desktop"
ICON_FILE="$HOME/.local/share/icons/autologin.png"

# Execução principal: remove config, binário e atalhos.
echo "Iniciando Limpeza: Suricato AutoLogin v1.1"

# Remove arquivos de configuração e credenciais (CUIDADO: deleta a senha mestra)
if [ -d "$CONFIG_DIR" ]; then
    echo "Removendo configurações em $CONFIG_DIR"
    rm -rf "$CONFIG_DIR"
fi

# Remove o binário compilado
if [ -f "$BIN_PATH" ]; then
    echo "Removendo executável..."
    rm "$BIN_PATH"
fi

# Remove atalhos do sistema
rm -f "$DESKTOP_FILE"
rm -f "$ICON_FILE"
rm -f "$HOME/Desktop/Suricato AutoLogin.desktop"

echo "Sistema limpo por Gustavo Pires."