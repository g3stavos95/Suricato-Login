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
echo "🔹 1/6 Removendo dependências Python (pip --user)..."

python3 -m pip uninstall -y \
  PyAutoGUI MouseInfo PyGetWindow PyMsgBox PyRect PyScreeze pytweening pyperclip python-xlib \
  pynput evdev \
  pystray pillow \
  cryptography cffi \
  pyinstaller pyinstaller-hooks-contrib altgraph \
  >/dev/null 2>&1 || true

echo "✔ Dependências Python removidas"

echo
echo "🔹 2/6 Removendo arquivos instalados pelo Suricato..."

rm -f "$HOME/Apps/autologin"
rm -f "$HOME/.local/share/applications/autologin.desktop"
rm -f "$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")/Suricato AutoLogin.desktop"
rm -f "$HOME/.local/share/icons/autologin.png"
rm -rf "$HOME/.cache/autologin"
rm -f "$HOME/.autologin.txt"

update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "✔ Arquivos do projeto removidos"

echo
echo "🔹 3/6 Removendo dependências de sistema (APT)..."
echo "   (pode pedir senha de administrador)"

sudo apt remove -y \
  zenity \
  python3-pip \
  python3-tk \
  scrot \
  >/dev/null 2>&1 || true

sudo apt autoremove -y >/dev/null 2>&1 || true

echo "✔ Dependências de sistema removidas"

echo
echo "🔹 4/6 Limpando cache do pip..."

rm -rf "$HOME/.cache/pip"

echo "✔ Cache limpo"

echo
echo "🔹 5/6 Verificações finais..."

command -v zenity >/dev/null 2>&1 || echo "✔ zenity AUSENTE"
python3 -m pip --version >/dev/null 2>&1 || echo "✔ pip AUSENTE"
python3 - << 'EOF' >/dev/null 2>&1 || echo "✔ libs Python removidas"
import pyautogui
EOF

echo
echo "🔹 6/6 Ambiente pronto para teste"

echo
echo "============================================"
echo " ✅ RESET CONCLUÍDO"
echo
echo " O sistema está pronto para testar:"
echo "   bash autologin_setup.sh"
echo
echo " Dica: se quiser teste perfeito, use outro usuário."
echo "============================================"