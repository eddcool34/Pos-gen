#!/bin/bash
set -e

echo "=== POS-GEN Sistema Punto de Venta ==="

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
  echo "Creando entorno virtual..."
  python3 -m venv venv
fi

# Activate and install dependencies
source venv/bin/activate
echo "Instalando dependencias..."
pip install -q -r requirements.txt

# Start the app
echo ""
echo "Iniciando servidor en http://localhost:5000"
echo "Usuario: admin | Contraseña: admin123"
echo ""
python app.py
