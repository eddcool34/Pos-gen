# POS-GEN — Sistema Punto de Venta

Sistema de punto de venta sencillo y completo para negocios al menudeo.
Construido con **Python/Flask** + **SQLite** + **Bootstrap 5**.

---

## Características

| Módulo | Descripción |
|---|---|
| **Autenticación** | Login por usuario con roles (Admin / Cajero) |
| **Turnos** | Abrir y cerrar turno diario con efectivo de apertura/cierre |
| **Vender (POS)** | Pantalla táctil con carrito, búsqueda y filtro por categoría |
| **Inventario** | Crear, editar y eliminar productos con control de stock |
| **Reportes** | Ventas por periodo con descarga en PDF |
| **Configuración** | Nombre, logo, dirección, teléfono y gestión de usuarios |

---

## Inicio rápido

```bash
# Clonar / entrar al directorio
cd Pos-gen

# Opción A — script automático
bash run.sh

# Opción B — manual
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abre `http://localhost:5000` en tu navegador.

**Credenciales por defecto:** `admin` / `admin123`

---

## Estructura

```
Pos-gen/
├── app.py              # Backend Flask (rutas, BD, PDF)
├── requirements.txt    # Dependencias Python
├── run.sh              # Script de inicio
├── pos.db              # Base de datos SQLite (se crea al iniciar)
├── static/
│   ├── css/style.css   # Estilos personalizados
│   └── uploads/        # Logos subidos
└── templates/
    ├── base.html        # Layout con sidebar
    ├── login.html
    ├── dashboard.html
    ├── shift_open.html
    ├── shift_close.html
    ├── pos.html         # Interfaz de venta
    ├── inventory.html
    ├── config.html
    └── reports.html
```

---

## Flujo de uso

1. **Login** → ingresar con usuario y contraseña
2. **Abrir turno** → registrar efectivo de apertura
3. **Inventario** → cargar los productos con precio y stock
4. **Vender** → seleccionar productos, cobrar (efectivo o tarjeta)
5. **Reportes** → consultar ventas del día / periodo y descargar PDF
6. **Cerrar turno** → registrar efectivo final y ver resumen del día

---

## Dependencias

- Flask ≥ 3.0
- fpdf2 ≥ 2.7 (generación de PDF)
- Pillow ≥ 10.0
- Werkzeug ≥ 3.0
