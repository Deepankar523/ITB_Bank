from flask import Flask, request, redirect, session, render_template, flash
from db import get_db_connection
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta

app = Flask(__name__)
app.secret_key = "itb_bank_super_secret_2024"

FD_RATES = {3: 6.0, 6: 6.5, 12: 7.0, 24: 7.5, 36: 8.0}

# ───────── HELPERS ─────────

def fix_email(email):
    if "@" not in email:
        return email + "@itb.org"
    return email

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def ensure_admin():
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE email='admin@itb.org'")
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (name,email,password,role) VALUES (%s,%s,%s,%s)",
            ("Admin", "admin@itb.org", "1234", "admin")
        )
        db.commit()
    db.close()

# ───────── ROUTES ─────────

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/create', methods=['GET','POST'])
def create():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        pin = request.form['pin']
        amount = request.form['amount']

        db = get_db_connection()
        cur = db.cursor(dictionary=True)

        cur.execute("INSERT INTO users (name,email,password) VALUES (%s,%s,%s)",
                    (name,email,pin))
        uid = cur.lastrowid

        acc = "ACC" + str(uid).zfill(4)

        cur.execute("INSERT INTO accounts (user_id,account_number,balance) VALUES (%s,%s,%s)",
                    (uid,acc,amount))

        db.commit()
        db.close()

        return render_template('create_success.html', acc=acc)

    return render_template('create.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = fix_email(request.form['email'])
        pin = request.form['pin']

        db = get_db_connection()
        cur = db.cursor(dictionary=True)

        cur.execute("SELECT * FROM users WHERE email=%s AND password=%s",(email,pin))
        user = cur.fetchone()

        db.close()

        if not user:
            return render_template('login.html', error="Invalid credentials")

        session['user_id'] = user['user_id']
        session['role'] = user['role']

        return redirect('/admin' if user['role']=="admin" else '/dashboard')

    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT * FROM accounts WHERE user_id=%s",(session['user_id'],))
    acc = cur.fetchone()

    db.close()
    return render_template('dashboard.html', account=acc)

# ───────── ADMIN (FIXED) ─────────

@app.route('/admin')
@admin_required
def admin():
    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT * FROM users WHERE role!='admin'")
    customers = cur.fetchall()

    db.close()

    return render_template('admin.html', customers=customers)

# ───────── SHOW (FIXED) ─────────

@app.route('/show')
@admin_required
def show():
    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT * FROM users WHERE role!='admin'")
    data = cur.fetchall()

    db.close()

    return render_template('show.html', data=data)

# ───────── LOAN (SIMPLIFIED) ─────────

@app.route('/loan', methods=['GET','POST'])
@login_required
def loan():
    return render_template('loan.html')

# ───────── RUN ─────────

if __name__ == "__main__":
    ensure_admin()
    app.run(debug=True)