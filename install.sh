#!/data/data/com.termux/files/usr/bin/bash
# Instalador de Orion Code para Termux.
set -euo pipefail

VERSION="3.13.1"
echo ""
echo "  Orion Code ${VERSION}"
echo ""

if [ -z "${PREFIX:-}" ] || [ ! -d "${PREFIX}/bin" ]; then
  echo "Este instalador es solo para Termux."
  echo "En escritorio ejecuta: python3 orion_code.py"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
for f in orion_code.py orion_brain.py requirements.txt; do
  if [ ! -f "$SCRIPT_DIR/$f" ]; then
    echo "ERROR: falta $f junto a install.sh"
    exit 1
  fi
done

if ! command -v python3 >/dev/null 2>&1; then
  pkg update -y
  pkg install -y python
fi
if ! command -v git >/dev/null 2>&1; then
  pkg install -y git
fi

echo "Instalando dependencias obligatorias..."
if ! python3 -m pip install --user -r "$SCRIPT_DIR/requirements.txt"; then
  echo ""
  echo "ERROR: no se pudieron instalar las dependencias obligatorias."
  echo "Revisa el mensaje de pip de arriba y vuelve a ejecutar install.sh."
  exit 1
fi

if [ -f "$SCRIPT_DIR/requirements-optional.txt" ]; then
  echo "Instalando extras opcionales (TUI)..."
  if ! python3 -m pip install --user -r "$SCRIPT_DIR/requirements-optional.txt"; then
    echo "Aviso: no se instalaron los extras. Orion funcionará en modo clásico (orion --cli)."
  fi
fi

INSTALL_DIR="$HOME/.orion-code"
mkdir -p "$INSTALL_DIR/brain"
for f in orion_code.py orion_brain.py orion_tui.py orion_dashboard.py README.md; do
  if [ -f "$SCRIPT_DIR/$f" ]; then
    cp -f "$SCRIPT_DIR/$f" "$INSTALL_DIR/$f"
  fi
done
chmod +x "$INSTALL_DIR/orion_code.py"


cat > "$PREFIX/bin/orion" <<'WRAP'
#!/data/data/com.termux/files/usr/bin/sh
exec python3 "$HOME/.orion-code/orion_code.py" "$@"
WRAP
chmod +x "$PREFIX/bin/orion"
ln -sf "$PREFIX/bin/orion" "$PREFIX/bin/orion-code"

if [ ! -d "$HOME/storage" ]; then
  termux-setup-storage || echo "Aviso: no se concedió acceso al almacenamiento (solo afecta a /backup compartir)."
fi

echo ""
echo "Instalado. Ejecuta: orion"
echo "API key: https://aistudio.google.com/apikey"
