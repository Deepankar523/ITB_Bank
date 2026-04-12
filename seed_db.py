import random
from decimal import Decimal
from datetime import date, timedelta
from db import get_db_connection

def seed_database():
    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    # Continuing without wiping data to add more new accounts

    first_names = ["Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anjali", "Rohan", "Neha", "Karan", "Pooja", 
                   "Suresh", "Ramesh", "Deepa", "Kavita", "Sanjay", "Rajesh", "Aarti", "Sunil", "Manish", "Anita"]
    last_names = ["Sharma", "Verma", "Singh", "Patel", "Kumar", "Gupta", "Das", "Joshi", "Mishra", "Reddy",
                  "Yadav", "Chauhan", "Rao", "Nair", "Iyer", "Pandey", "Agarwal", "Mehta", "Bhat", "Deshmukh"]
    
    import uuid
    for i in range(1, 101):
        name = f"{random.choice(first_names)} {random.choice(last_names)}"
        email = f"user_{uuid.uuid4().hex[:6]}@example.com"
        pin = f"{random.randint(1000, 9999)}"
        phone = f"98765{random.randint(10000, 99999)}"
        
        # Determine created_at in the past
        days_ago = random.randint(10, 400)
        created_at_dt = date.today() - timedelta(days=days_ago)

        cur.execute(
            "INSERT INTO users (name, email, password, role, phone, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (name, email, pin, "customer", phone, created_at_dt)
        )
        user_id = cur.lastrowid

        acc_num = "ACC" + str(user_id).zfill(4)
        balance = random.randint(5000, 150000)
        
        cur.execute(
            "INSERT INTO accounts (user_id, account_number, balance, account_type) VALUES (%s, %s, %s, %s)",
            (user_id, acc_num, balance, random.choice(["savings", "current"]))
        )
        
        # Generate some transactions
        txn_count = random.randint(2, 25)
        for _ in range(txn_count):
            txn_amt = random.randint(100, 5000)
            txn_type = random.choice(["deposit", "withdrawal"])
            cur.execute(
                "INSERT INTO transactions (from_account, to_account, amount, txn_type, description) VALUES (%s, %s, %s, %s, %s)",
                (acc_num if txn_type == "withdrawal" else None, 
                 acc_num if txn_type == "deposit" else None, 
                 txn_amt, txn_type, "Seeded transaction")
            )

        # Generate some loans
        if random.random() < 0.3: # 30% chance to have a loan
            loan_amt = random.randint(10000, 200000)
            status = random.choice(['pending', 'approved', 'closed'])
            amount_paid = 0
            if status == 'approved':
                amount_paid = random.randint(1000, loan_amt // 2)
            elif status == 'closed':
                amount_paid = loan_amt * 1.15
            
            cur.execute(
                "INSERT INTO loans (user_id, account_number, amount, purpose, duration_months, interest_rate, emi, credit_score, status, amount_paid) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, acc_num, loan_amt, "Personal", 12, 14.0, loan_amt * 0.09, random.randint(400, 800), status, amount_paid)
            )

    db.commit()
    print("Database seeded successfully with 60 accounts.")
    db.close()

if __name__ == "__main__":
    seed_database()
