from database import get_db_connection

def get_all_users():
    """Retrieve registered users without exposing password hashes."""

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
         cursor.execute("""
             SELECT id, username, email, role, is_active, created_at
             FROM users
             ORDER BY id ASC
         """)

         return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()
def update_user_role(user_id, new_role, acting_username):
    """Update a user's role safely."""
    if new_role not in ("admin", "user"):
        return False, "Invalid role."
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            "SELECT username,role From users WHERE id = %s FOR UPDATE",
            (user_id,)
        )
        target = cursor.fetchone()
        if not target:
            connection.rollback()
            return False, "User not found."
        if target["username"] == acting_username:
            connection.rollback()
            return False, "You cannot change your own role."
        if target["role"] == "admin" and new_role == "user":
            cursor.execute(
                "SELECT COUNT(*) AS total FROM users WHERE role = %s",
                ("admin",)
            )
            result = cursor.fetchone()
            if result["total"] <= 1:
                connection.rollback()
                return False, "At least one administrator must remain."
        cursor.execute(
            "UPDATE users SET role = %s WHERE username = %s",
            (new_role, target["username"])
        )
        connection.commit()
        return True, "User role updated successfully."
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

def toggle_user_status(user_id, desired_status, acting_username):
    """Set a user's account status safely."""
    if desired_status not in (0, 1):
         return False, "Invalid account status."

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            "SELECT id, username, role, is_active FROM users WHERE id = %s FOR UPDATE",
            (user_id,)
        )
        target = cursor.fetchone()
        if not target:
            connection.rollback()
            return False, "User not found."
        if target["username"] == acting_username:
            connection.rollback()
            return False, "You cannot change your own account status."
        if int(target["is_active"]) == desired_status:
            connection.rollback()
            return True, "Account status is already set."

        if target["role"] == "admin" and desired_status == 0:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM users WHERE role = %s AND is_active = 1",
                ("admin",)
            )
            result = cursor.fetchone()
            if result["total"] <= 1:
                connection.rollback()

                return False, "At least one active administrator must remain."
        cursor.execute(
            "UPDATE `users` SET `is_active` = %s WHERE `id` = %s",
            (desired_status, user_id)
        )
        connection.commit()
        if desired_status == 0:
            return True, "User deactivated successfully."
 
        return True, "User activated successfully."
         
    except BaseException:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

def delete_user(user_id, acting_username):
    """Delete a user while protecting the current and last admin."""

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            "SELECT id, username, role From users Where id = %s FOR UPDATE",
            (user_id,)
        )
        target = cursor.fetchone()
        if not target:
            connection.rollback()
            return false, "User not found."
        if target["username"] == acting_username:
            connection.rollback()
            return False, "You cannot delete your own account."

        if target["role"] == "admin":
            cursor.execute(
                "SELECT COUNT(*) AS total FROM users WHERE role = %s",
                ("admin",)
            )
            result = cursor.fetchone()
            if result["total"] <= 1:
                connection.rollback()
                return False, "You cannot delet the last administrator."
        cursor.execute(
            "DELETE FROM users WHERE id = %s",
            (user_id,)
        )
        connection.commit()
        return True, "User deleted successfully."

    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()
def update_user_details(user_id, new_username, new_email, acting_username):
    """Update another user's username and email."""
    new_username = new_username.strip()
    new_email = new_email.strip()
    if not new_username or not new_email:
        return False, "Username and email are required."
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, username FROM users WHERE id = %s",
             (user_id,)
        )
        target = cursor.fetchone()
        if not target:
            return False, "User not found."
        if target["username"] == acting_username:
            return False, "You cannot edit your own account here."
        cursor.execute(
            "UPDATE users SET username = %s, email =%s WHERE id = %s",
            (new_username, new_email, user_id)
        )
        connection.commit()
        return True, "User details updated successfully."
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()
