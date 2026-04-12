import sys
import time
sys.path.append('.')
from db import get_db_connection

def check_count():
    for _ in range(300):
        try:
            db = get_db_connection()
            c = db.cursor()
            c.execute("SELECT COUNT(*) FROM users")
            count = c.fetchone()[0]
            db.close()
            return count
        except Exception as e:
            print(f"Waiting for connections to clear... {e}", flush=True)
            time.sleep(5)
    return -1

if __name__ == '__main__':
    count = check_count()
    print("CURRENT USER COUNT:", count, flush=True)
