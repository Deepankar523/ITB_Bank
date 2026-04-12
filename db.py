
import mysql.connector
import os

def get_db_connection():
    return mysql.connector.connect(
        host="sql12.freesqldatabase.com",
        user="sql12822951",
        password="Sitarama010874",
        database="sql12822951",
        port=3306
    )