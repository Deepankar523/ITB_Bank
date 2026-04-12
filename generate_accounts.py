import mysql.connector
import random
import time
from decimal import Decimal

def get_db_connection():
    return mysql.connector.connect(
        host="sql12.freesqldatabase.com",
        user="sql12822951",
        password="NCvHVqAwpj",
        database="sql12822951",
        port=3306
        # Added to prevent auto close logic in connector if needed
    )

first_names = ["John", "Jane", "Alice", "Bob", "Charlie", "David", "Eve", "Frank", "Grace", "Heidi", "Ivan", "Judy", "Mallory", "Victor", "Peggy", "Trudy", "Trent", "Walter", "Arthur", "Betty", "Carl", "Diana", "Fiona", "George", "Harry", "Irene", "Jack"]
last_names = ["Smith", "Doe", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee"]

def generate_accounts(num_accounts=150):
    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True)
    except:
        print("Failed initial connect")
        return
    
    success = 0
    while success < num_accounts:
        try:
            name = f"{random.choice(first_names)} {random.choice(last_names)}"
            email = f"user_{random.randint(1000000, 9999999)}@example.com"
            pin = str(random.randint(1000, 9999))
            phone = f"987{random.randint(1000000, 9999999)}"
            amount_dec = Decimal(str(random.randint(5000, 500000)))
            acc_type = random.choice(['savings', 'current'])
            
            # Insert user
            cur.execute(
                "INSERT INTO users (name,email,password,phone) VALUES (%s,%s,%s,%s)",
                (name, email, pin, phone)
            )
            uid = cur.lastrowid
            acc = "ACC" + str(uid).zfill(4)
            
            # Insert account
            cur.execute(
                "INSERT INTO accounts (user_id,account_number,balance,account_type) "
                "VALUES (%s,%s,%s,%s)",
                (uid, acc, amount_dec, acc_type)
            )
            
            # Insert transaction
            cur.execute(
                "INSERT INTO transactions (to_account,amount,txn_type,description) "
                "VALUES (%s,%s,'deposit','Opening deposit')",
                (acc, amount_dec)
            )
            db.commit()
            success += 1
            if success % 10 == 0:
                print(f"Created account {success}/{num_accounts}")
            time.sleep(0.5) 
        except Exception as err: # Broad exception to catch MySQLInterfaceError
            print(f"Error: {err}, reconnecting...")
            try:
                db.close()
            except:
                pass
            time.sleep(2)
            try:
                db = get_db_connection()
                cur = db.cursor(dictionary=True)
            except Exception as e:
                print("Failed to reconnect:", e)
                time.sleep(5)
            
    try:
        db.close()
    except:
        pass
    print(f"Successfully created {success} accounts.")

if __name__ == "__main__":
    generate_accounts(150)
