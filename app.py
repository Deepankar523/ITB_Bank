
from flask import Flask, request, redirect, session, render_template, flash, send_file
from db import get_db_connection
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta
import io

app = Flask(__name__)
app.secret_key = "itb_bank_super_secret_2024"

FD_RATES = {3: 6.0, 6: 6.5, 12: 7.0, 24: 7.5, 36: 8.0}

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
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
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE email='admin@itb.org'")
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (name,email,password,role) VALUES (%s,%s,%s,%s)",
            ("Admin", "admin@itb.org", "1234", "admin")
        )
        db.commit()
    db.close()

def calc_credit_score(user_id):
    """
    Returns (score 300-900, band str, auto_approve bool)
    Factors: balance, account age, txn count, active/closed loans
    """
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)

    cur.execute(
        "SELECT a.balance, u.created_at "
        "FROM accounts a JOIN users u ON a.user_id = u.user_id "
        "WHERE a.user_id=%s", (user_id,)
    )
    acc     = cur.fetchone()
    balance = float(acc['balance']) if acc else 0
    acc_age = (date.today() - acc['created_at'].date()).days if acc else 0

    txn_count = 0
    if acc:
        cur.execute(
            "SELECT account_number FROM accounts WHERE user_id=%s", (user_id,)
        )
        a = cur.fetchone()
        if a:
            cur.execute(
                "SELECT COUNT(*) as c FROM transactions "
                "WHERE from_account=%s OR to_account=%s",
                (a['account_number'], a['account_number'])
            )
            txn_count = cur.fetchone()['c']

    cur.execute(
        "SELECT COUNT(*) as c FROM loans WHERE user_id=%s AND status='approved'",
        (user_id,)
    )
    active_loans = cur.fetchone()['c']

    cur.execute(
        "SELECT COUNT(*) as c FROM loans WHERE user_id=%s AND status='closed'",
        (user_id,)
    )
    closed_loans = cur.fetchone()['c']
    db.close()

    score = 300
    if balance >= 10000:    score += 80
    if balance >= 50000:    score += 100
    if balance >= 100000:   score += 120
    if acc_age  >= 30:      score += 60
    if acc_age  >= 180:     score += 80
    if txn_count >= 5:      score += 60
    if txn_count >= 20:     score += 60
    if closed_loans >= 1:   score += 80
    if active_loans == 0:   score += 60
    elif active_loans >= 2: score -= 80
    score = max(300, min(900, score))

    if score >= 750:   band, approved = "Excellent", True
    elif score >= 650: band, approved = "Good",      True
    elif score >= 550: band, approved = "Fair",      False
    else:              band, approved = "Poor",      False
    return score, band, approved

# ─────────────────────────────────────────────
#  PUBLIC ROUTES
# ─────────────────────────────────────────────
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/create', methods=['GET','POST'])
def create():
    if request.method == 'POST':
        name     = request.form.get('name','').strip()
        email    = request.form.get('email','').strip()
        pin      = request.form.get('pin','').strip()
        amount   = request.form.get('amount','').strip()
        phone    = request.form.get('phone','').strip()
        acc_type = request.form.get('account_type','savings')
        errors   = []
        if not name:   errors.append("Name is required.")
        if not email:  errors.append("Email is required.")
        if not pin:    errors.append("PIN is required.")
        if not amount: errors.append("Opening amount is required.")
        if errors:
            return render_template('create.html', errors=errors,
                                   name=name, email=email, pin=pin, amount=amount)
        try:
            amount_dec = Decimal(amount)
        except InvalidOperation:
            return render_template('create.html', errors=["Invalid amount entered."],
                                   name=name, email=email, pin=pin, amount=amount)
        if amount_dec < 5000:
            return render_template('create.html',
                                   errors=["Minimum opening amount is ₹5000."],
                                   name=name, email=email, pin=pin, amount=amount)
        db  = get_db_connection()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT user_id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            db.close()
            return render_template('create.html',
                                   errors=["This email is already registered."],
                                   name=name, email=email, pin=pin, amount=amount)
        cur.execute(
            "INSERT INTO users (name,email,password,phone) VALUES (%s,%s,%s,%s)",
            (name, email, pin, phone or None)
        )
        uid = cur.lastrowid
        acc = "ACC" + str(uid).zfill(4)
        cur.execute(
            "INSERT INTO accounts (user_id,account_number,balance,account_type) "
            "VALUES (%s,%s,%s,%s)",
            (uid, acc, amount_dec, acc_type)
        )
        cur.execute(
            "INSERT INTO transactions (to_account,amount,txn_type,description) "
            "VALUES (%s,%s,'deposit','Opening deposit')",
            (acc, amount_dec)
        )
        db.commit(); db.close()
        return render_template('create_success.html', acc=acc, amount=amount_dec)
    return render_template('create.html', errors=[], name='', email='', pin='', amount='')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = fix_email(request.form.get('email','').strip())
        pin   = request.form.get('pin','').strip()
        if not email or not pin:
            return render_template('login.html', error="Please enter both email and PIN.")
        db  = get_db_connection()
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM users WHERE email=%s AND password=%s", (email, pin)
        )
        user = cur.fetchone(); db.close()
        if not user:
            return render_template('login.html',
                                   error="Account does not exist or wrong PIN.")
        session['user_id'] = user['user_id']
        session['role']    = user['role']
        session['name']    = user['name']
        return redirect('/admin' if user['role'] == 'admin' else '/dashboard')
    return render_template('login.html', error=None)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/delete', methods=['GET','POST'])
def delete():
    if request.method == 'POST':
        raw   = request.form.get('email','').strip()
        if not raw:
            return render_template('delete.html', error="Please enter an email.")
        email = fix_email(raw)
        if email.lower() == "admin@itb.org":
            return render_template('delete.html', error="Admin account cannot be deleted.")
        db  = get_db_connection()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        if not user:
            db.close()
            return render_template('delete.html', error="Account does not exist.")
        cur.execute("SELECT balance FROM accounts WHERE user_id=%s", (user['user_id'],))
        row     = cur.fetchone()
        balance = row['balance'] if row else 0
        cur.execute("DELETE FROM fixed_deposits WHERE user_id=%s", (user['user_id'],))
        cur.execute("DELETE FROM loans        WHERE user_id=%s", (user['user_id'],))
        cur.execute("DELETE FROM accounts     WHERE user_id=%s", (user['user_id'],))
        cur.execute("DELETE FROM users        WHERE user_id=%s", (user['user_id'],))
        db.commit(); db.close()
        return render_template('delete_success.html', balance=balance)
    return render_template('delete.html', error=None)

# ─────────────────────────────────────────────
#  CUSTOMER ROUTES
# ─────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM accounts WHERE user_id=%s", (session['user_id'],))
    acc = cur.fetchone(); db.close()
    return render_template('dashboard.html', account=acc)

@app.route('/deposit', methods=['POST'])
@login_required
def deposit():
    raw = request.form.get('amount','').strip()
    if not raw:
        flash("Please enter a deposit amount.", "error")
        return redirect('/dashboard')
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        flash("Invalid amount.", "error"); return redirect('/dashboard')
    if amount <= 0:
        flash("Amount must be positive.", "error"); return redirect('/dashboard')
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT account_number FROM accounts WHERE user_id=%s", (session['user_id'],)
    )
    acc = cur.fetchone()
    cur.execute(
        "UPDATE accounts SET balance=balance+%s WHERE user_id=%s",
        (amount, session['user_id'])
    )
    cur.execute(
        "INSERT INTO transactions (to_account,amount,txn_type,description) "
        "VALUES (%s,%s,'deposit','Deposit')",
        (acc['account_number'], amount)
    )
    db.commit(); db.close()
    flash(f"₹{amount:,.2f} deposited successfully!", "success")
    return redirect('/dashboard')

@app.route('/withdraw', methods=['POST'])
@login_required
def withdraw():
    raw = request.form.get('amount','').strip()
    if not raw:
        flash("Please enter a withdrawal amount.", "error")
        return redirect('/dashboard')
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        flash("Invalid amount.", "error"); return redirect('/dashboard')
    if amount <= 0:
        flash("Amount must be positive.", "error"); return redirect('/dashboard')
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT account_number, balance FROM accounts WHERE user_id=%s",
        (session['user_id'],)
    )
    acc = cur.fetchone()
    if acc['balance'] - amount < Decimal('5000'):
        flash("Minimum ₹5000 must remain in account.", "error")
        db.close(); return redirect('/dashboard')
    cur.execute(
        "UPDATE accounts SET balance=balance-%s WHERE user_id=%s",
        (amount, session['user_id'])
    )
    cur.execute(
        "INSERT INTO transactions (from_account,amount,txn_type,description) "
        "VALUES (%s,%s,'withdrawal','Withdrawal')",
        (acc['account_number'], amount)
    )
    db.commit(); db.close()
    flash(f"₹{amount:,.2f} withdrawn successfully!", "success")
    return redirect('/dashboard')

@app.route('/transfer', methods=['GET','POST'])
@login_required
def transfer():
    if request.method == 'POST':
        to_acc = request.form.get('receiver_account','').strip()
        raw    = request.form.get('amount','').strip()
        errors = []
        if not to_acc: errors.append("Receiver account number is required.")
        if not raw:    errors.append("Amount is required.")
        if errors:
            return render_template('transfer.html', errors=errors)
        try:
            amount = Decimal(raw)
        except InvalidOperation:
            return render_template('transfer.html', errors=["Invalid amount."])
        if amount <= 0:
            return render_template('transfer.html', errors=["Amount must be positive."])
        db  = get_db_connection()
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT account_number,balance FROM accounts WHERE user_id=%s",
            (session['user_id'],)
        )
        my_acc = cur.fetchone()
        cur.execute(
            "SELECT account_number FROM accounts WHERE account_number=%s", (to_acc,)
        )
        dest = cur.fetchone()
        if not dest:
            db.close()
            return render_template('transfer.html',
                                   errors=["Destination account not found."])
        if to_acc == my_acc['account_number']:
            db.close()
            return render_template('transfer.html',
                                   errors=["Cannot transfer to your own account."])
        if my_acc['balance'] - amount < Decimal('5000'):
            db.close()
            return render_template('transfer.html',
                                   errors=["Insufficient balance (₹5000 must remain)."])
        cur.execute(
            "UPDATE accounts SET balance=balance-%s WHERE account_number=%s",
            (amount, my_acc['account_number'])
        )
        cur.execute(
            "UPDATE accounts SET balance=balance+%s WHERE account_number=%s",
            (amount, to_acc)
        )
        cur.execute(
            "INSERT INTO transactions "
            "(from_account,to_account,amount,txn_type,description) "
            "VALUES (%s,%s,%s,'transfer','Fund Transfer')",
            (my_acc['account_number'], to_acc, amount)
        )
        db.commit(); db.close()
        flash(f"₹{amount:,.2f} transferred to {to_acc} successfully!", "success")
        return redirect('/dashboard')
    return render_template('transfer.html', errors=[])

@app.route('/history')
@login_required
def history():
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT account_number FROM accounts WHERE user_id=%s", (session['user_id'],)
    )
    acc  = cur.fetchone()
    txns = []
    acc_num = ''
    if acc:
        acc_num = acc['account_number']
        cur.execute(
            "SELECT * FROM transactions "
            "WHERE from_account=%s OR to_account=%s ORDER BY txn_date DESC",
            (acc_num, acc_num)
        )
        txns = cur.fetchall()
    db.close()
    return render_template('history.html', transactions=txns, account_number=acc_num)

# ─────────────────────────────────────────────
#  PROFILE
# ─────────────────────────────────────────────
@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_pin':
            old_pin  = request.form.get('old_pin','').strip()
            new_pin  = request.form.get('new_pin','').strip()
            conf_pin = request.form.get('confirm_pin','').strip()
            cur.execute(
                "SELECT password FROM users WHERE user_id=%s", (session['user_id'],)
            )
            row = cur.fetchone()
            if row['password'] != old_pin:
                flash("Current PIN is incorrect.", "error")
            elif not new_pin:
                flash("New PIN cannot be empty.", "error")
            elif new_pin != conf_pin:
                flash("New PINs do not match.", "error")
            elif len(new_pin) < 4:
                flash("PIN must be at least 4 characters.", "error")
            else:
                cur.execute(
                    "UPDATE users SET password=%s WHERE user_id=%s",
                    (new_pin, session['user_id'])
                )
                db.commit()
                flash("PIN changed successfully!", "success")
        elif action == 'update_phone':
            phone = request.form.get('phone','').strip()
            if not phone:
                flash("Please enter a phone number.", "error")
            else:
                cur.execute(
                    "UPDATE users SET phone=%s WHERE user_id=%s",
                    (phone, session['user_id'])
                )
                db.commit()
                flash("Phone number updated!", "success")

    cur.execute(
        "SELECT u.*, a.account_number, a.balance, a.account_type, "
        "u.created_at AS acc_created "
        "FROM users u JOIN accounts a ON u.user_id=a.user_id "
        "WHERE u.user_id=%s",
        (session['user_id'],)
    )
    user = cur.fetchone(); db.close()
    if not user:
        flash("Profile not found.", "error")
        return redirect('/dashboard')
    return render_template('profile.html', user=user)

# ─────────────────────────────────────────────
#  FIXED DEPOSIT
# ─────────────────────────────────────────────
@app.route('/fd', methods=['GET','POST'])
@login_required
def fixed_deposit():
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    if request.method == 'POST':
        raw_amt  = request.form.get('amount','').strip()
        raw_dur  = request.form.get('duration','').strip()
        errors   = []
        if not raw_amt: errors.append("Amount is required.")
        if not raw_dur: errors.append("Duration is required.")
        amount   = None
        duration = None
        if not errors:
            try:
                amount   = Decimal(raw_amt)
                duration = int(raw_dur)
            except (InvalidOperation, ValueError):
                errors.append("Invalid values entered.")
        if not errors:
            cur.execute(
                "SELECT account_number, balance FROM accounts WHERE user_id=%s",
                (session['user_id'],)
            )
            acc = cur.fetchone()
            if amount < 1000:
                errors.append("Minimum FD amount is ₹1000.")
            elif duration not in FD_RATES:
                errors.append("Invalid duration selected.")
            elif acc['balance'] - amount < Decimal('5000'):
                errors.append(
                    f"Insufficient balance. You have ₹{float(acc['balance']):,.2f} "
                    f"but ₹5000 must remain after creating FD."
                )
            else:
                rate         = FD_RATES[duration]
                maturity_amt = round(float(amount) * (1 + (rate/100) * (duration/12)), 2)
                start        = date.today()
                maturity     = start + timedelta(days=duration * 30)
                cur.execute(
                    "UPDATE accounts SET balance=balance-%s WHERE user_id=%s",
                    (amount, session['user_id'])
                )
                cur.execute(
                    "INSERT INTO fixed_deposits "
                    "(user_id,account_number,amount,rate,duration_months,"
                    "start_date,maturity_date,maturity_amount) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (session['user_id'], acc['account_number'], amount, rate,
                     duration, start, maturity, maturity_amt)
                )
                cur.execute(
                    "INSERT INTO transactions "
                    "(from_account,amount,txn_type,description) "
                    "VALUES (%s,%s,'withdrawal','FD Created')",
                    (acc['account_number'], amount)
                )
                db.commit()
                flash(
                    f"FD of ₹{float(amount):,.2f} created! "
                    f"Matures on {maturity.strftime('%d %b %Y')} "
                    f"with ₹{maturity_amt:,.2f}",
                    "success"
                )
                db.close(); return redirect('/fd')
        cur.execute(
            "SELECT * FROM fixed_deposits WHERE user_id=%s ORDER BY start_date DESC",
            (session['user_id'],)
        )
        fds = cur.fetchall(); db.close()
        return render_template('fd.html', fds=fds, rates=FD_RATES, errors=errors)

    cur.execute(
        "SELECT * FROM fixed_deposits WHERE user_id=%s ORDER BY start_date DESC",
        (session['user_id'],)
    )
    fds = cur.fetchall(); db.close()
    return render_template('fd.html', fds=fds, rates=FD_RATES, errors=[])

@app.route('/fd/withdraw/<int:fd_id>', methods=['POST'])
@login_required
def fd_withdraw(fd_id):
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT * FROM fixed_deposits WHERE fd_id=%s AND user_id=%s",
        (fd_id, session['user_id'])
    )
    fd = cur.fetchone()
    if not fd or fd['status'] != 'active':
        flash("FD not found or already closed.", "error")
        db.close(); return redirect('/fd')
    cur.execute(
        "UPDATE accounts SET balance=balance+%s WHERE user_id=%s",
        (fd['maturity_amount'], session['user_id'])
    )
    cur.execute(
        "UPDATE fixed_deposits SET status='withdrawn' WHERE fd_id=%s", (fd_id,)
    )
    cur.execute(
        "SELECT account_number FROM accounts WHERE user_id=%s", (session['user_id'],)
    )
    acc = cur.fetchone()
    cur.execute(
        "INSERT INTO transactions (to_account,amount,txn_type,description) "
        "VALUES (%s,%s,'deposit','FD Withdrawn')",
        (acc['account_number'], fd['maturity_amount'])
    )
    db.commit(); db.close()
    flash(
        f"FD withdrawn! ₹{float(fd['maturity_amount']):,.2f} credited to your account.",
        "success"
    )
    return redirect('/fd')

# ─────────────────────────────────────────────
#  LOAN
# ─────────────────────────────────────────────
@app.route('/loan', methods=['GET','POST'])
@login_required
def loan():
    credit_score, cibil_band, auto_approve = calc_credit_score(session['user_id'])
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)

    if request.method == 'POST':
        raw_amt  = request.form.get('amount','').strip()
        purpose  = request.form.get('purpose','').strip()
        raw_dur  = request.form.get('duration','').strip()
        errors   = []
        if not raw_amt: errors.append("Loan amount is required.")
        if not purpose: errors.append("Purpose is required.")
        if not raw_dur: errors.append("Duration is required.")
        amount   = None
        duration = None
        if not errors:
            try:
                amount   = Decimal(raw_amt)
                duration = int(raw_dur)
            except (InvalidOperation, ValueError):
                errors.append("Invalid values entered.")
        if not errors:
            if amount < 1000:
                errors.append("Minimum loan amount is ₹1000.")
            elif credit_score < 550:
                errors.append(
                    f"Loan rejected. Your CIBIL score ({credit_score}) is too low. "
                    f"Minimum required: 550."
                )
            elif duration not in [6, 12, 24, 36, 60]:
                errors.append("Invalid duration selected.")
            else:
                rate         = 12.0 if credit_score >= 750 else (14.0 if credit_score >= 650 else 18.0)
                monthly_rate = rate / 100 / 12
                n            = duration
                emi          = float(amount) * monthly_rate * (1+monthly_rate)**n / ((1+monthly_rate)**n - 1)
                status       = 'approved' if auto_approve else 'pending'
                cur.execute(
                    "SELECT account_number FROM accounts WHERE user_id=%s",
                    (session['user_id'],)
                )
                acc = cur.fetchone()
                cur.execute(
                    "INSERT INTO loans "
                    "(user_id,account_number,amount,purpose,duration_months,"
                    "interest_rate,emi,credit_score,status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (session['user_id'], acc['account_number'], amount, purpose,
                     duration, rate, round(emi, 2), credit_score, status)
                )
                if status == 'approved':
                    cur.execute(
                        "UPDATE accounts SET balance=balance+%s WHERE user_id=%s",
                        (amount, session['user_id'])
                    )
                    cur.execute(
                        "INSERT INTO transactions "
                        "(to_account,amount,txn_type,description) "
                        "VALUES (%s,%s,'deposit','Loan Disbursed')",
                        (acc['account_number'], amount)
                    )
                db.commit()
                flash(
                    "Loan approved & disbursed! ✅" if status == 'approved'
                    else "Application submitted. Pending admin approval. ⏳",
                    "success"
                )
                db.close(); return redirect('/loan')

        cur.execute(
            "SELECT * FROM loans WHERE user_id=%s ORDER BY applied_at DESC",
            (session['user_id'],)
        )
        loans = cur.fetchall(); db.close()
        return render_template('loan.html', loans=loans, errors=errors,
                               credit_score=credit_score, cibil_band=cibil_band)

    cur.execute(
        "SELECT * FROM loans WHERE user_id=%s ORDER BY applied_at DESC",
        (session['user_id'],)
    )
    loans = cur.fetchall(); db.close()
    return render_template('loan.html', loans=loans, errors=[],
                           credit_score=credit_score, cibil_band=cibil_band)

@app.route('/loan/repay/<int:loan_id>', methods=['POST'])
@login_required
def repay_loan(loan_id):
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT * FROM loans WHERE loan_id=%s AND user_id=%s",
        (loan_id, session['user_id'])
    )
    loan_row = cur.fetchone()
    if not loan_row or loan_row['status'] != 'approved':
        flash("Loan not found or not active.", "error")
        db.close(); return redirect('/loan')
    cur.execute(
        "SELECT account_number, balance FROM accounts WHERE user_id=%s",
        (session['user_id'],)
    )
    acc = cur.fetchone()
    emi = float(loan_row['emi'])
    if float(acc['balance']) < emi:
        flash("Insufficient balance to pay EMI.", "error")
        db.close(); return redirect('/loan')
    new_paid  = float(loan_row['amount_paid']) + emi
    total_due = float(loan_row['amount']) * (
        1 + float(loan_row['interest_rate']) / 100 * loan_row['duration_months'] / 12
    )
    new_status = 'closed' if new_paid >= total_due else 'approved'
    cur.execute(
        "UPDATE accounts SET balance=balance-%s WHERE user_id=%s",
        (emi, session['user_id'])
    )
    cur.execute(
        "UPDATE loans SET amount_paid=%s, status=%s WHERE loan_id=%s",
        (new_paid, new_status, loan_id)
    )
    cur.execute(
        "INSERT INTO transactions "
        "(from_account,amount,txn_type,description) "
        "VALUES (%s,%s,'withdrawal','Loan EMI Repayment')",
        (acc['account_number'], emi)
    )
    db.commit(); db.close()
    flash(
        f"EMI ₹{emi:,.2f} paid! "
        f"{'🎉 Loan fully repaid!' if new_status == 'closed' else ''}",
        "success"
    )
    return redirect('/loan')

# ─────────────────────────────────────────────
#  PDF STATEMENT
# ─────────────────────────────────────────────
@app.route('/statement/pdf')
@login_required
def statement_pdf():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import (SimpleDocTemplate, Table,
                                        TableStyle, Paragraph, Spacer)
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        flash("PDF library missing. Run: pip install reportlab", "error")
        return redirect('/history')

    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT u.*, a.account_number, a.balance, a.account_type "
        "FROM users u JOIN accounts a ON u.user_id=a.user_id "
        "WHERE u.user_id=%s",
        (session['user_id'],)
    )
    user = cur.fetchone()
    if not user:
        db.close(); flash("Account not found.", "error"); return redirect('/dashboard')
    cur.execute(
        "SELECT * FROM transactions "
        "WHERE from_account=%s OR to_account=%s "
        "ORDER BY txn_date DESC LIMIT 10",
        (user['account_number'], user['account_number'])
    )
    txns = cur.fetchall(); db.close()

    buf    = io.BytesIO()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               topMargin=40, bottomMargin=40,
                               leftMargin=40, rightMargin=40)
    styles = getSampleStyleSheet()
    story  = []
    story.append(Paragraph("<b>ITB BANK</b>", styles['Title']))
    story.append(Paragraph("Mini Account Statement", styles['Heading2']))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>Name:</b> {user['name']}", styles['Normal']))
    story.append(Paragraph(
        f"<b>Account:</b> {user['account_number']}  |  "
        f"<b>Type:</b> {user['account_type'].capitalize()}",
        styles['Normal']
    ))
    story.append(Paragraph(
        f"<b>Balance:</b> Rs.{float(user['balance']):,.2f}", styles['Normal']
    ))
    story.append(Paragraph(
        f"<b>Generated:</b> {date.today().strftime('%d %b %Y')}", styles['Normal']
    ))
    story.append(Spacer(1, 14))

    rows = [["#", "Type", "Amount", "Description", "Date"]]
    for i, t in enumerate(txns, 1):
        is_credit = (t['txn_type'] == 'deposit' or
                     (t['txn_type'] == 'transfer' and
                      t['to_account'] == user['account_number']))
        sign = "+" if is_credit else "-"
        rows.append([
            str(i),
            t['txn_type'].capitalize(),
            f"{sign}Rs.{float(t['amount']):,.2f}",
            t['description'] or '-',
            t['txn_date'].strftime('%d %b %Y')
        ])

    tbl = Table(rows, colWidths=[25, 75, 95, 215, 85])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0),  colors.HexColor('#1a73e8')),
        ('TEXTCOLOR',  (0,0), (-1,0),  colors.white),
        ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,1), (-1,-1),
         [colors.white, colors.HexColor('#f0f4f8')]),
        ('GRID', (0,0), (-1,-1), 0.4, colors.HexColor('#dde3ec')),
        ('ALIGN', (2,0), (2,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWHEIGHT', (0,0), (-1,-1), 18),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "This is a system-generated statement. — ITB Bank", styles['Italic']
    ))
    doc.build(story)
    buf.seek(0)
    fname = f"ITB_Statement_{user['account_number']}.pdf"
    return send_file(buf, download_name=fname,
                     as_attachment=True, mimetype='application/pdf')

# ─────────────────────────────────────────────
#  ADMIN ROUTES
# ─────────────────────────────────────────────
@app.route('/admin')
@admin_required
def admin():
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT COUNT(*) as c FROM users WHERE role='customer'")
    total_users = cur.fetchone()['c']
    cur.execute("SELECT COALESCE(SUM(balance),0) as s FROM accounts")
    total_balance = float(cur.fetchone()['s'])
    cur.execute("SELECT COUNT(*) as c FROM transactions")
    total_txns = cur.fetchone()['c']

    cur.execute("SELECT * FROM transactions ORDER BY txn_date DESC LIMIT 15")
    recent_txns = cur.fetchall()

    cur.execute("""
        SELECT l.*, u.name AS uname, a.account_number AS acc_no
        FROM loans l
        JOIN users u ON l.user_id = u.user_id
        JOIN accounts a ON a.user_id = l.user_id
        WHERE l.status = 'pending'
    """)
    pending_loans = cur.fetchall()

    # Full customer data with credit scores, loan totals
    cur.execute("""
        SELECT
            u.user_id, u.name, u.email, u.phone,
            a.account_number, a.balance, a.account_type, u.created_at,
            COALESCE(SUM(CASE WHEN l.status='approved' THEN l.amount ELSE 0 END),0) AS active_loan_amt,
            COALESCE(SUM(CASE WHEN l.status='approved' THEN l.amount_paid ELSE 0 END),0) AS loan_paid,
            COUNT(CASE WHEN l.status='approved' THEN 1 END) AS active_loans,
            COUNT(CASE WHEN l.status='closed'   THEN 1 END) AS closed_loans
        FROM users u
        JOIN accounts a ON u.user_id = a.user_id
        LEFT JOIN loans l ON l.user_id = u.user_id
        WHERE u.email != 'admin@itb.org'
        GROUP BY u.user_id, u.name, u.email, u.phone,
                 a.account_number, a.balance, a.account_type, u.created_at
    """)
    raw_customers = cur.fetchall()
    db.close()

    # Attach credit scores
    customers = []
    for c in raw_customers:
        score, band, _ = calc_credit_score(c['user_id'])
        c['credit_score'] = score
        c['cibil_band']   = band
        customers.append(c)

    return render_template('admin.html',
        total_users=total_users,
        total_balance=total_balance,
        total_txns=total_txns,
        customers=customers,
        recent_txns=recent_txns,
        pending_loans=pending_loans
    )

@app.route('/show')
@admin_required
def show():
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            u.user_id, u.name, u.email, u.password, u.phone,
            a.account_number, a.balance, a.account_type, u.created_at,
            COALESCE(SUM(CASE WHEN l.status='approved' THEN l.amount ELSE 0 END),0) AS active_loan_amt
        FROM users u
        JOIN accounts a ON u.user_id = a.user_id
        LEFT JOIN loans l ON l.user_id = u.user_id
        WHERE u.email != 'admin@itb.org'
        GROUP BY u.user_id, u.name, u.email, u.password, u.phone,
                 a.account_number, a.balance, a.account_type, u.created_at
        ORDER BY u.name
    """)
    raw_data = cur.fetchall(); db.close()

    data = []
    for c in raw_data:
        score, band, _ = calc_credit_score(c['user_id'])
        c['credit_score'] = score
        c['cibil_band']   = band
        data.append(c)

    return render_template('show.html', data=data)

@app.route('/admin/loan/<int:loan_id>/<action>')
@admin_required
def admin_loan_action(loan_id, action):
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM loans WHERE loan_id=%s", (loan_id,))
    loan_row = cur.fetchone()
    if loan_row:
        if action == 'approve':
            cur.execute(
                "UPDATE loans SET status='approved' WHERE loan_id=%s", (loan_id,)
            )
            cur.execute(
                "UPDATE accounts SET balance=balance+%s WHERE user_id=%s",
                (loan_row['amount'], loan_row['user_id'])
            )
            cur.execute(
                "SELECT account_number FROM accounts WHERE user_id=%s",
                (loan_row['user_id'],)
            )
            acc = cur.fetchone()
            cur.execute(
                "INSERT INTO transactions "
                "(to_account,amount,txn_type,description) "
                "VALUES (%s,%s,'deposit','Loan Approved & Disbursed')",
                (acc['account_number'], loan_row['amount'])
            )
            flash("Loan approved and amount disbursed.", "success")
        elif action == 'reject':
            cur.execute(
                "UPDATE loans SET status='rejected' WHERE loan_id=%s", (loan_id,)
            )
            flash("Loan rejected.", "success")
    db.commit(); db.close()
    return redirect('/admin')

@app.route('/admin/user/<int:uid>/loans')
@admin_required
def admin_user_loans(uid):
    db  = get_db_connection()
    cur = db.cursor(dictionary=True)
    
    cur.execute(
        "SELECT u.name, u.email, a.account_number "
        "FROM users u JOIN accounts a ON u.user_id = a.user_id "
        "WHERE u.user_id=%s", (uid,)
    )
    user_info = cur.fetchone()
    
    if not user_info:
        flash("User not found.", "error")
        db.close()
        return redirect('/admin')
        
    cur.execute("SELECT * FROM loans WHERE user_id=%s ORDER BY applied_at DESC", (uid,))
    loans = cur.fetchall()
    db.close()
    
    for l in loans:
        rate = float(l['interest_rate'])
        dur = l['duration_months']
        amt = float(l['amount'])
        paid = float(l['amount_paid'])
        total_due = amt * (1 + (rate/100.0) * (dur/12.0))
        l['total_due'] = total_due
        l['remaining'] = max(0.0, total_due - paid)
        
    return render_template('admin_user_loans.html', user_info=user_info, loans=loans)

if __name__ == "__main__":
    ensure_admin()

