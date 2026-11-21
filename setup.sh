#!/data/data/com.termux/files/usr/bin/bash
# Configuración de Orion Code desde el repositorio (GitHub) en Termux.
# Uso: bash setup.sh   (desde cualquier carpeta; no hace falta cd al repo)
set -euo pipefail

echo "=========================================="
echo "  Configurando entorno de Orion Code..."
echo "=========================================="

if [ -z "${PREFIX:-}" ] || [ ! -d "${PREFIX}/bin" ]; then
  echo "Este script es solo para Termux."
  exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
MAIN_SCRIPT="$REPO_DIR/orion_code.py"

if [ ! -f "$MAIN_SCRIPT" ]; then
  echo "ERROR: no encuentro orion_code.py en $REPO_DIR"
  exit 1
fi
if [ ! -f "$REPO_DIR/requirements.txt" ]; then
  echo "ERROR: no encuentro requirements.txt en $REPO_DIR"
  exit 1
fi

echo "[1/5] Actualizando paquetes de Termux..."
pkg update -y
pkg upgrade -y

echo "[2/5] Instalando git, python y compiladores..."
pkg install -y git python clang make libffi openssl

echo "[3/5] Instalando dependencias de Python..."
python3 -m pip install --upgrade pip
if ! python3 -m pip install --user -r "$REPO_DIR/requirements.txt"; then
  echo "ERROR: fallaron las dependencias obligatorias (requirements.txt)."
  echo "Revisa el mensaje de pip de arriba y vuelve a ejecutar setup.sh."
  exit 1
fi
if [ -f "$REPO_DIR/requirements-optional.txt" ]; then
  if ! python3 -m pip install --user -r "$REPO_DIR/requirements-optional.txt"; then
    echo "Aviso: no se instalaron los extras de la TUI. Orion usará el modo clásico (orion --cli)."
  fi
fi

echo "[4/5] Configurando almacenamiento..."
if [ ! -d "$HOME/storage" ]; then
  termux-setup-storage || echo "Aviso: no se concedió acceso al almacenamiento (solo afecta a /backup compartir)."
fi

echo "[5/5] Creando el comando 'orion'..."
BIN="$PREFIX/bin/orion"
# Sin cd: 'orion' se ejecuta en la carpeta desde la que lo llamas (importante para git y @archivos).
cat > "$BIN" <<WRAP
#!/data/data/com.termux/files/usr/bin/sh
exec python3 "$MAIN_SCRIPT" "\$@"
WRAP
chmod +x "$BIN"
ln -sf "$BIN" "$PREFIX/bin/orion-code"

echo "=================================================="
echo "  ¡Instalación completa!"
echo "  Ahora escribe: orion"
echo "=================================================="
