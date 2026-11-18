
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection

def register_user(username, email,password):
    connection = get_db_connection()
    cursor = connection.cursor()

    password_hash = generate_password_hash(password)

    try:
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
             (username, email, password_hash)
        )
        connection.commit()
        return True
    finally:
        cursor.close()
        connection.close()
def verify_user(username, password):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
       cursor.execute(
           "SELECT * FROM users WHERE username = %s",
            (username,)
       )
       user = cursor.fetchone()

       if user and check_password_hash(user["password_hash"], password):
           if not user.get("is_active", True):
               return None
           return user

       return None
    finally:
         cursor.close()
         connection.close()
def change_password(username, current_password, new_password):
    """Change the password for the currently logged-in user."""
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, password_hash
            FROM users
            WHERE username = %s AND is_active = 1
            """,
            (username,)
        )
        user = cursor.fetchone()
        if not user:
            return False, "User account not found or inactive."
        if not check_password_hash(
            user["password_hash"],
            current_password
        ):
            return False, "Current password is incorrect."
        if check_password_hash(
            user["password_hash"],
            new_password
        ):
            return False, "New password must be different."
        new_hash = generate_password_hash(new_password)
        cursor.execute(
            """
            UPDATE users
            SET password_hash = %s
            WHERE id = %s
            """,
            (new_hash, user["id"])
        )
        connection.commit()
        return True, "Password changed successfully."
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()        
