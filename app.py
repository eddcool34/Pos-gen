from flask import (Flask, render_template, request, jsonify, session,
                   redirect, url_for, send_file, flash)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime, date
import os
import sqlite3
from fpdf import FPDF
import io

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'pos-secret-key-change-me')

UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
DATABASE = 'pos.db'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY,
            business_name TEXT DEFAULT 'Mi Negocio',
            address TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            logo TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'cashier',
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            open_time TEXT NOT NULL,
            close_time TEXT,
            opening_cash REAL DEFAULT 0,
            closing_cash REAL,
            status TEXT DEFAULT 'open',
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 0,
            category TEXT DEFAULT 'General',
            barcode TEXT DEFAULT '',
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            total REAL NOT NULL,
            payment_method TEXT DEFAULT 'cash',
            amount_paid REAL DEFAULT 0,
            change_given REAL DEFAULT 0,
            FOREIGN KEY (shift_id) REFERENCES shifts(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (sale_id) REFERENCES sales(id)
        );
    ''')
    c.execute('SELECT id FROM config WHERE id = 1')
    if not c.fetchone():
        c.execute('INSERT INTO config VALUES (1,"Mi Negocio","","","")')
    c.execute('SELECT id FROM users WHERE username="admin"')
    if not c.fetchone():
        hashed = generate_password_hash('admin123')
        c.execute('INSERT INTO users (username,password,role) VALUES ("admin",?,"admin")',
                  (hashed,))
    conn.commit()
    conn.close()


def allowed_file(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def shift_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'shift_id' not in session:
            flash('Debes abrir un turno primero.', 'warning')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Solo los administradores pueden hacer esto.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Context processor
# ---------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    conn = get_db()
    cfg = conn.execute('SELECT * FROM config WHERE id=1').fetchone()
    conn.close()
    return {'config': dict(cfg) if cfg else {}, 'now': datetime.now()}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        user = conn.execute(
            'SELECT * FROM users WHERE username=? AND active=1', (username,)
        ).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            # Restore open shift if any
            conn = get_db()
            shift = conn.execute(
                'SELECT id FROM shifts WHERE user_id=? AND status="open"',
                (user['id'],)
            ).fetchone()
            conn.close()
            if shift:
                session['shift_id'] = shift['id']
            flash(f'Bienvenido, {user["username"]}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Usuario o contraseña incorrectos.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    shift = None
    if 'shift_id' in session:
        shift = conn.execute(
            'SELECT s.*,u.username FROM shifts s '
            'JOIN users u ON s.user_id=u.id WHERE s.id=?',
            (session['shift_id'],)
        ).fetchone()

    stats = {'sales_count': 0, 'total': 0.0}
    recent = []
    if 'shift_id' in session:
        row = conn.execute(
            'SELECT COUNT(*) as cnt, COALESCE(SUM(total),0) as total '
            'FROM sales WHERE shift_id=?', (session['shift_id'],)
        ).fetchone()
        stats = {'sales_count': row['cnt'], 'total': row['total']}
        recent = conn.execute(
            'SELECT * FROM sales WHERE shift_id=? ORDER BY date DESC LIMIT 6',
            (session['shift_id'],)
        ).fetchall()

    low_stock = conn.execute(
        'SELECT * FROM products WHERE stock<=5 AND active=1 ORDER BY stock ASC LIMIT 5'
    ).fetchall()
    conn.close()
    return render_template('dashboard.html', shift=shift, stats=stats,
                           recent=recent, low_stock=low_stock)


# ---------------------------------------------------------------------------
# Shift
# ---------------------------------------------------------------------------

@app.route('/shift/open', methods=['GET', 'POST'])
@login_required
def shift_open():
    if 'shift_id' in session:
        flash('Ya tienes un turno abierto.', 'warning')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        opening_cash = float(request.form.get('opening_cash', 0) or 0)
        conn = get_db()
        c = conn.cursor()
        c.execute(
            'INSERT INTO shifts (user_id,open_time,opening_cash,status) '
            'VALUES (?,?,?,"open")',
            (session['user_id'], datetime.now().isoformat(), opening_cash)
        )
        session['shift_id'] = c.lastrowid
        conn.commit()
        conn.close()
        flash('Turno abierto exitosamente.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('shift_open.html')


@app.route('/shift/close', methods=['GET', 'POST'])
@login_required
def shift_close():
    if 'shift_id' not in session:
        return redirect(url_for('dashboard'))
    conn = get_db()
    shift = conn.execute('SELECT * FROM shifts WHERE id=?',
                         (session['shift_id'],)).fetchone()
    summary = conn.execute(
        'SELECT COUNT(*) as cnt, COALESCE(SUM(total),0) as total '
        'FROM sales WHERE shift_id=?', (session['shift_id'],)
    ).fetchone()
    if request.method == 'POST':
        closing_cash = float(request.form.get('closing_cash', 0) or 0)
        conn.execute(
            'UPDATE shifts SET close_time=?,closing_cash=?,status="closed" WHERE id=?',
            (datetime.now().isoformat(), closing_cash, session['shift_id'])
        )
        conn.commit()
        conn.close()
        session.pop('shift_id', None)
        flash('Turno cerrado exitosamente.', 'success')
        return redirect(url_for('dashboard'))
    conn.close()
    return render_template('shift_close.html', shift=shift, summary=summary)


# ---------------------------------------------------------------------------
# POS – Vender
# ---------------------------------------------------------------------------

@app.route('/pos')
@login_required
@shift_required
def pos():
    conn = get_db()
    products = conn.execute(
        'SELECT * FROM products WHERE active=1 AND stock>0 ORDER BY category,name'
    ).fetchall()
    categories = conn.execute(
        'SELECT DISTINCT category FROM products WHERE active=1 ORDER BY category'
    ).fetchall()
    conn.close()
    return render_template('pos.html', products=products, categories=categories)


@app.route('/pos/sale', methods=['POST'])
@login_required
@shift_required
def create_sale():
    data = request.get_json()
    items = data.get('items', [])
    payment_method = data.get('payment_method', 'cash')
    amount_paid = float(data.get('amount_paid', 0))

    if not items:
        return jsonify({'success': False, 'error': 'Carrito vacío'})

    conn = get_db()
    c = conn.cursor()
    total = sum(float(i['price']) * int(i['quantity']) for i in items)
    change = round(amount_paid - total, 2) if payment_method == 'cash' else 0.0

    try:
        c.execute(
            'INSERT INTO sales (shift_id,user_id,date,total,payment_method,amount_paid,change_given) '
            'VALUES (?,?,?,?,?,?,?)',
            (session['shift_id'], session['user_id'], datetime.now().isoformat(),
             total, payment_method, amount_paid, change)
        )
        sale_id = c.lastrowid
        for item in items:
            product = conn.execute(
                'SELECT * FROM products WHERE id=?', (item['id'],)
            ).fetchone()
            if not product or product['stock'] < int(item['quantity']):
                conn.rollback()
                name = product['name'] if product else 'producto'
                return jsonify({'success': False,
                                'error': f'Stock insuficiente: {name}'})
            subtotal = round(float(item['price']) * int(item['quantity']), 2)
            c.execute(
                'INSERT INTO sale_items '
                '(sale_id,product_id,product_name,quantity,price,subtotal) '
                'VALUES (?,?,?,?,?,?)',
                (sale_id, item['id'], item['name'],
                 item['quantity'], item['price'], subtotal)
            )
            c.execute('UPDATE products SET stock=stock-? WHERE id=?',
                      (item['quantity'], item['id']))
        conn.commit()
        return jsonify({'success': True, 'sale_id': sale_id,
                        'total': total, 'change': change})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

@app.route('/inventory')
@login_required
def inventory():
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '').strip()
    conn = get_db()
    query = 'SELECT * FROM products WHERE active=1'
    params = []
    if q:
        query += ' AND name LIKE ?'
        params.append(f'%{q}%')
    if cat:
        query += ' AND category=?'
        params.append(cat)
    query += ' ORDER BY category,name'
    products = conn.execute(query, params).fetchall()
    categories = conn.execute(
        'SELECT DISTINCT category FROM products WHERE active=1 ORDER BY category'
    ).fetchall()
    conn.close()
    return render_template('inventory.html', products=products,
                           categories=categories, q=q, cat=cat)


@app.route('/inventory/add', methods=['POST'])
@login_required
def inventory_add():
    name = request.form.get('name', '').strip()
    price = request.form.get('price', '0')
    stock = request.form.get('stock', '0')
    category = request.form.get('category', 'General').strip() or 'General'
    barcode = request.form.get('barcode', '').strip()
    if not name or float(price) <= 0:
        flash('Nombre y precio son requeridos.', 'danger')
        return redirect(url_for('inventory'))
    conn = get_db()
    conn.execute(
        'INSERT INTO products (name,price,stock,category,barcode) VALUES (?,?,?,?,?)',
        (name, float(price), int(stock), category, barcode)
    )
    conn.commit()
    conn.close()
    flash(f'Producto "{name}" agregado.', 'success')
    return redirect(url_for('inventory'))


@app.route('/inventory/edit/<int:pid>', methods=['POST'])
@login_required
def inventory_edit(pid):
    name = request.form.get('name', '').strip()
    price = float(request.form.get('price', 0))
    stock = int(request.form.get('stock', 0))
    category = request.form.get('category', 'General').strip() or 'General'
    barcode = request.form.get('barcode', '').strip()
    conn = get_db()
    conn.execute(
        'UPDATE products SET name=?,price=?,stock=?,category=?,barcode=? WHERE id=?',
        (name, price, stock, category, barcode, pid)
    )
    conn.commit()
    conn.close()
    flash('Producto actualizado.', 'success')
    return redirect(url_for('inventory'))


@app.route('/inventory/delete/<int:pid>', methods=['POST'])
@login_required
def inventory_delete(pid):
    conn = get_db()
    conn.execute('UPDATE products SET active=0 WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    flash('Producto eliminado.', 'success')
    return redirect(url_for('inventory'))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@app.route('/config')
@login_required
@admin_required
def config():
    conn = get_db()
    users = conn.execute(
        'SELECT id,username,role,active FROM users ORDER BY id'
    ).fetchall()
    conn.close()
    return render_template('config.html', users=users)


@app.route('/config/update', methods=['POST'])
@login_required
@admin_required
def config_update():
    business_name = request.form.get('business_name', '').strip()
    address = request.form.get('address', '').strip()
    phone = request.form.get('phone', '').strip()

    conn = get_db()
    if 'logo' in request.files and request.files['logo'].filename:
        f = request.files['logo']
        if allowed_file(f.filename):
            filename = secure_filename(f.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            f.save(filepath)
            conn.execute(
                'UPDATE config SET business_name=?,address=?,phone=?,logo=? WHERE id=1',
                (business_name, address, phone, f'uploads/{filename}')
            )
        else:
            flash('Formato de imagen no válido.', 'danger')
            conn.close()
            return redirect(url_for('config'))
    else:
        conn.execute(
            'UPDATE config SET business_name=?,address=?,phone=? WHERE id=1',
            (business_name, address, phone)
        )
    conn.commit()
    conn.close()
    flash('Configuración guardada.', 'success')
    return redirect(url_for('config'))


@app.route('/config/user/add', methods=['POST'])
@login_required
@admin_required
def user_add():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'cashier')
    if not username or not password:
        flash('Usuario y contraseña son requeridos.', 'danger')
        return redirect(url_for('config'))
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO users (username,password,role) VALUES (?,?,?)',
            (username, generate_password_hash(password), role)
        )
        conn.commit()
        flash(f'Usuario "{username}" creado.', 'success')
    except Exception:
        flash('Ese nombre de usuario ya existe.', 'danger')
    finally:
        conn.close()
    return redirect(url_for('config'))


@app.route('/config/user/toggle/<int:uid>', methods=['POST'])
@login_required
@admin_required
def user_toggle(uid):
    if uid == session.get('user_id'):
        flash('No puedes desactivar tu propio usuario.', 'danger')
        return redirect(url_for('config'))
    conn = get_db()
    user = conn.execute('SELECT active FROM users WHERE id=?', (uid,)).fetchone()
    if user:
        conn.execute('UPDATE users SET active=? WHERE id=?',
                     (0 if user['active'] else 1, uid))
        conn.commit()
    conn.close()
    flash('Usuario actualizado.', 'success')
    return redirect(url_for('config'))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@app.route('/reports')
@login_required
def reports():
    date_from = request.args.get('date_from', date.today().isoformat())
    date_to = request.args.get('date_to', date.today().isoformat())
    conn = get_db()
    sales = conn.execute(
        'SELECT s.*,u.username FROM sales s '
        'JOIN users u ON s.user_id=u.id '
        'WHERE DATE(s.date) BETWEEN ? AND ? ORDER BY s.date DESC',
        (date_from, date_to)
    ).fetchall()
    total = sum(s['total'] for s in sales)
    # Payment breakdown
    cash_total = sum(s['total'] for s in sales if s['payment_method'] == 'cash')
    card_total = sum(s['total'] for s in sales if s['payment_method'] == 'card')
    conn.close()
    return render_template('reports.html', sales=sales, total=total,
                           cash_total=cash_total, card_total=card_total,
                           date_from=date_from, date_to=date_to)


@app.route('/reports/pdf')
@login_required
def reports_pdf():
    date_from = request.args.get('date_from', date.today().isoformat())
    date_to = request.args.get('date_to', date.today().isoformat())

    conn = get_db()
    cfg = conn.execute('SELECT * FROM config WHERE id=1').fetchone()
    sales = conn.execute(
        'SELECT s.*,u.username FROM sales s '
        'JOIN users u ON s.user_id=u.id '
        'WHERE DATE(s.date) BETWEEN ? AND ? ORDER BY s.date',
        (date_from, date_to)
    ).fetchall()
    items_map = {}
    for sale in sales:
        items_map[sale['id']] = conn.execute(
            'SELECT * FROM sale_items WHERE sale_id=?', (sale['id'],)
        ).fetchall()
    conn.close()

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Header
    pdf.set_font('Helvetica', 'B', 18)
    pdf.cell(0, 10, cfg['business_name'], ln=True, align='C')
    pdf.set_font('Helvetica', '', 10)
    if cfg['address']:
        pdf.cell(0, 6, cfg['address'], ln=True, align='C')
    if cfg['phone']:
        pdf.cell(0, 6, f'Tel: {cfg["phone"]}', ln=True, align='C')
    pdf.set_font('Helvetica', 'I', 9)
    period = f'Periodo: {date_from}  al  {date_to}'
    pdf.cell(0, 6, period, ln=True, align='C')
    pdf.ln(4)

    # Summary box
    total = sum(s['total'] for s in sales)
    cash_t = sum(s['total'] for s in sales if s['payment_method'] == 'cash')
    card_t = sum(s['total'] for s in sales if s['payment_method'] == 'card')
    pdf.set_fill_color(30, 42, 58)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(63, 9, f'Ventas: {len(sales)}', border=0, fill=True, align='C')
    pdf.cell(63, 9, f'Efectivo: ${cash_t:.2f}', border=0, fill=True, align='C')
    pdf.cell(64, 9, f'Tarjeta: ${card_t:.2f}', border=0, fill=True, align='C')
    pdf.ln()
    pdf.set_fill_color(39, 174, 96)
    pdf.cell(0, 10, f'TOTAL: ${total:.2f}', border=0, fill=True, align='C',
             ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # Table header
    col_w = [15, 42, 35, 30, 30, 28]
    headers = ['#', 'Fecha/Hora', 'Cajero', 'Metodo', 'Total', 'Cambio']
    pdf.set_fill_color(44, 62, 80)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Helvetica', 'B', 8)
    for h, w in zip(headers, col_w):
        pdf.cell(w, 7, h, border=1, fill=True, align='C')
    pdf.ln()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font('Helvetica', '', 8)

    for idx, sale in enumerate(sales):
        fill = idx % 2 == 0
        if fill:
            pdf.set_fill_color(245, 245, 245)
        dt = sale['date'][:16] if sale['date'] else ''
        row = [str(sale['id']), dt, sale['username'],
               sale['payment_method'].upper(),
               f'${sale["total"]:.2f}', f'${sale["change_given"]:.2f}']
        aligns = ['C', 'C', 'C', 'C', 'R', 'R']
        for val, w, align in zip(row, col_w, aligns):
            pdf.cell(w, 6, val, border=1, fill=fill, align=align)
        pdf.ln()

    # Footer total
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_fill_color(39, 174, 96)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(sum(col_w[:4]), 7, 'TOTAL GENERAL', border=1, fill=True, align='R')
    pdf.cell(col_w[4], 7, f'${total:.2f}', border=1, fill=True, align='R')
    pdf.cell(col_w[5], 7, '', border=1, fill=True)
    pdf.ln()

    pdf.set_text_color(150, 150, 150)
    pdf.set_font('Helvetica', 'I', 7)
    pdf.cell(0, 8,
             f'Generado el {datetime.now().strftime("%d/%m/%Y %H:%M")}',
             ln=True, align='C')

    pdf_bytes = bytes(pdf.output())
    filename = f'ventas_{date_from}_{date_to}.pdf'
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
