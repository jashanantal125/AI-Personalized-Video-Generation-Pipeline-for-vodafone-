import pymysql

# ecore pswd : YOUR_DB_PASSWORD
# local db pswd : YOUR_LOCAL_DB_PASSWORD

def db_connection():
    try:
        print("hi")
        conn = pymysql.connect(
            host='127.0.0.1',
            user='root',
            password='YOUR_DB_PASSWORD',
            database='vi_auto',
            cursorclass=pymysql.cursors.DictCursor
        )
        # cursor = conn.cursor()
        return conn

    except Exception as e:
        print(f"Error : {e}")
        return None
