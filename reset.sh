#!/usr/bin/env bash
set -euo pipefail

echo "============================================"
echo " RESETANDO AMBIENTE PARA TESTE DO ZERO"
echo " Projeto: Suricato AutoLogin"
echo "============================================"
echo

read -r -p "⚠️ Isso removerá dependências e arquivos do projeto. Continuar? (s/N): " CONF
[[ "${CONF:-}" =~ ^[sS]$ ]] || exit 0

echo
echo "🔹 1/7 Removendo dependências Python (pip --user)..."

python3 -m pip uninstall -y \
  PyAutoGUI MouseInfo PyGetWindow PyMsgBox PyRect PyScreeze pytweening pyperclip python-xlib \
  pynput evdev \
  pystray pillow \
  cryptography cffi \
  pyinstaller pyinstaller-hooks-contrib altgraph \
  >/dev/null 2>&1 || true

echo "✔ Dependências Python removidas"

echo
echo "🔹 2/7 Removendo arquivos instalados pelo Suricato..."

rm -f "$HOME/Apps/autologin"
rm -f "$HOME/.local/share/applications/autologin.desktop"
rm -f "$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")/Suricato AutoLogin.desktop"
rm -f "$HOME/.local/share/icons/autologin.png"
rm -rf "$HOME/.cache/autologin"
rm -f "$HOME/.autologin.txt"

update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "✔ Arquivos do projeto removidos"

echo
echo "🔹 3/7 Removendo dependências GUI (APT)..."
echo "   (pode pedir senha de administrador)"

# GUI usadas pelo setup/app
sudo apt remove -y \
  yad \
  zenity \
  >/dev/null 2>&1 || true

echo "✔ GUI removidas"

echo
echo "🔹 4/7 Removendo dependências de sistema adicionais (APT)..."

# Dependências que o setup tenta instalar
sudo apt remove -y \
  python3-pip \
  python3-tk \
  scrot \
  >/dev/null 2>&1 || true

sudo apt autoremove -y >/dev/null 2>&1 || true

echo "✔ Dependências de sistema removidas"

echo
echo "🔹 5/7 Limpando cache do pip..."

rm -rf "$HOME/.cache/pip"

echo "✔ Cache limpo"

echo
echo "🔹 6/7 Verificações finais (o esperado é estar AUSENTE)..."

command -v yad >/dev/null 2>&1 || echo "✔ yad AUSENTE"
command -v zenity >/dev/null 2>&1 || echo "✔ zenity AUSENTE"
python3 -m pip --version >/dev/null 2>&1 || echo "✔ pip AUSENTE"
python3 - << 'EOF' >/dev/null 2>&1 || echo "✔ libs Python removidas"
import pyautogui, pynput, pystray, cryptography, PIL, PyInstaller  # noqa
EOF

echo
echo "🔹 7/7 Ambiente pronto para teste"

echo
echo "============================================"
echo " ✅ RESET CONCLUÍDO"
echo
echo " Agora teste:"
echo "   bash autologin_setup.sh"
echo "============================================"