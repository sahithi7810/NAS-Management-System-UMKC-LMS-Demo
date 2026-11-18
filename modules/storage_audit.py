
import os
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from modules.file_manager import STORAGE_FOLDER
from database import get_db_connection


logger = logging.getLogger(__name__)

# Default storage quota for each student: 5 GB
DEFAULT_QUOTA_BYTES = 5 * 1024 ** 3

# Send an alert when usage reaches 90%
ALERT_THRESHOLD = 90


# ==========================================================
# 1. CREATE STORAGE TRACKING TABLES
# ==========================================================

def init_storage_tables():
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS storage_file_records (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                owner_user_id INT NOT NULL,
                relative_path VARCHAR(1024) NOT NULL,
                filename VARCHAR(255) NOT NULL,
                size_bytes BIGINT NOT NULL DEFAULT 0,
                uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_deleted TINYINT(1) NOT NULL DEFAULT 0,
                deleted_at DATETIME NULL,
                deleted_by_user_id INT NULL,
                INDEX idx_storage_owner (owner_user_id, is_deleted),
                INDEX idx_storage_path (relative_path(191))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS storage_activity_logs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                actor_user_id INT NOT NULL,
                actor_username VARCHAR(100) NOT NULL,
                action VARCHAR(30) NOT NULL,
                relative_path VARCHAR(1024),
                filename VARCHAR(255),
                file_size_bytes BIGINT NOT NULL DEFAULT 0,
                details VARCHAR(500),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_storage_activity_user (actor_user_id),
                INDEX idx_storage_activity_date (created_at),
                INDEX idx_storage_activity_action (action)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS storage_user_quotas (
                user_id INT PRIMARY KEY,
                quota_bytes BIGINT NOT NULL,
                updated_at DATETIME NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS storage_alert_states (
                user_id INT PRIMARY KEY,
                above_90 TINYINT(1) NOT NULL DEFAULT 0,
                last_alert_at DATETIME NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        connection.commit()
        logger.info("Storage tracking tables initialized.")

    except Exception:
        connection.rollback()
        logger.exception("Storage tracking table initialization failed.")
        raise

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 2. GET USER INFORMATION
# ==========================================================

def get_user_information(username):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, username, email, role
            FROM users
            WHERE username = %s
        """, (username,))

        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 3. GET OR CREATE STUDENT STORAGE QUOTA
# ==========================================================

def get_quota_bytes(user_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            INSERT IGNORE INTO storage_user_quotas
                (user_id, quota_bytes)
            VALUES (%s, %s)
        """, (user_id, DEFAULT_QUOTA_BYTES))

        connection.commit()

        cursor.execute("""
            SELECT quota_bytes
            FROM storage_user_quotas
            WHERE user_id = %s
        """, (user_id,))

        row = cursor.fetchone()
        return int(row["quota_bytes"])

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 4. GET STUDENT STORAGE USAGE
# ==========================================================

def get_user_storage_summary(username):
    user = get_user_information(username)

    if not user:
        return None

    if user["role"] == "admin":
        return {
            "username": username,
            "is_admin": True,
            "used_bytes": 0,
            "quota_bytes": 0,
            "remaining_bytes": 0,
            "usage_percent": 0
        }

    user_id = user["id"]
    quota = get_quota_bytes(user_id)

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT COALESCE(SUM(size_bytes), 0) AS used_bytes
            FROM storage_file_records
            WHERE owner_user_id = %s
              AND is_deleted = 0
        """, (user_id,))

        row = cursor.fetchone()
        used = int(row["used_bytes"])

        remaining = max(quota - used, 0)

        percentage = (
            round((used / quota) * 100, 2)
            if quota > 0 else 0
        )

        return {
            "username": username,
            "email": user["email"],
            "user_id": user_id,
            "is_admin": False,
            "used_bytes": used,
            "quota_bytes": quota,
            "remaining_bytes": remaining,
            "usage_percent": percentage
        }

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 5. CHECK WHETHER STUDENT CAN UPLOAD
# ==========================================================

def can_user_upload(username, incoming_size):
    user = get_user_information(username)

    if not user:
        return False, "User account not found."

    # Professors/admins are not restricted by student quotas.
    if user["role"] == "admin":
        return True, "Administrator upload allowed."

    if incoming_size < 0:
        return False, "Invalid file size."

    summary = get_user_storage_summary(username)

    if not summary:
        return False, "Could not calculate storage usage."

    if incoming_size > summary["remaining_bytes"]:
        return False, (
            "Storage quota exceeded. "
            "Please remove files or contact your professor."
        )

    return True, "Storage available."


# ==========================================================
# 6. WRITE AN ACTIVITY RECORD
# ==========================================================

def _insert_activity(
    cursor,
    user,
    action,
    relative_path=None,
    filename=None,
    file_size=0,
    details=None
):
    cursor.execute("""
        INSERT INTO storage_activity_logs
        (
            actor_user_id,
            actor_username,
            action,
            relative_path,
            filename,
            file_size_bytes,
            details
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        user["id"],
        user["username"],
        action,
        relative_path,
        filename,
        int(file_size or 0),
        details
    ))


# ==========================================================
# 7. RECORD A SUCCESSFUL UPLOAD
# ==========================================================

def record_upload(username, relative_path, file_size):
    user = get_user_information(username)

    if not user:
        raise RuntimeError("Uploading user does not exist.")

    filename = Path(relative_path).name

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # Insert current file ownership.
        cursor.execute("""
            INSERT INTO storage_file_records
            (
                owner_user_id,
                relative_path,
                filename,
                size_bytes
            )
            VALUES (%s, %s, %s, %s)
        """, (
            user["id"],
            relative_path,
            filename,
            int(file_size)
        ))

        _insert_activity(
            cursor,
            user,
            "upload",
            relative_path,
            filename,
            file_size,
            "File uploaded successfully."
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    # Send an email to the student if usage reaches 90%.
    if user["role"] != "admin":
        check_storage_email_alert(username)


# ==========================================================
# 8. RECORD A FILE DOWNLOAD
# ==========================================================

def record_download(username, relative_path, file_size=0):
    user = get_user_information(username)

    if not user:
        return

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        _insert_activity(
            cursor,
            user,
            "download",
            relative_path,
            Path(relative_path).name,
            file_size,
            "File downloaded."
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 9. RECORD A FILE DELETION
# ==========================================================

def record_delete(username, relative_path, file_size=0):
    user = get_user_information(username)

    if not user:
        raise RuntimeError("Deleting user does not exist.")

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE storage_file_records
            SET is_deleted = 1,
                deleted_at = NOW(),
                deleted_by_user_id = %s
            WHERE relative_path = %s
              AND is_deleted = 0
        """, (user["id"], relative_path))

        _insert_activity(
            cursor,
            user,
            "delete",
            relative_path,
            Path(relative_path).name,
            file_size,
            "File deleted successfully."
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    if user["role"] != "admin":
        check_storage_email_alert(username)


# ==========================================================
# 10. RECORD A RENAME
# ==========================================================

def record_rename(username, old_path, new_path):
    user = get_user_information(username)

    if not user:
        raise RuntimeError("Renaming user does not exist.")

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, relative_path
            FROM storage_file_records
            WHERE is_deleted = 0
              AND (
                    relative_path = %s
                    OR relative_path LIKE %s
              )
        """, (
            old_path,
            old_path.rstrip("/") + "/%"
        ))

        records = cursor.fetchall()

        for item in records:
            previous = item["relative_path"]
            suffix = previous[len(old_path):]
            updated = new_path + suffix

            cursor.execute("""
                UPDATE storage_file_records
                SET relative_path = %s,
                    filename = %s
                WHERE id = %s
            """, (
                updated,
                Path(updated).name,
                item["id"]
            ))

        _insert_activity(
            cursor,
            user,
            "rename",
            new_path,
            Path(new_path).name,
            0,
            f"Renamed from {old_path} to {new_path}."
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 11. SEND EMAIL TO THE STUDENT AT 90%
# ==========================================================

def send_student_storage_email(user, summary):
    mail_server = os.getenv("MAIL_SERVER")
    mail_port = int(os.getenv("MAIL_PORT", "587"))
    mail_username = os.getenv("MAIL_USERNAME")
    mail_password = os.getenv("MAIL_PASSWORD")

    use_tls = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    use_ssl = os.getenv("MAIL_USE_SSL", "false").lower() == "true"

    sender = os.getenv("MAIL_DEFAULT_SENDER") or mail_username

    if not all([
        mail_server,
        mail_username,
        mail_password,
        sender,
        user.get("email")
    ]):
        logger.warning(
            "Student storage email not sent: SMTP configuration missing."
        )
        return False

    used_gb = summary["used_bytes"] / (1024 ** 3)
    quota_gb = summary["quota_bytes"] / (1024 ** 3)
    remaining_gb = summary["remaining_bytes"] / (1024 ** 3)

    message = EmailMessage()

    message["Subject"] = "UMKC LMS Demo - Storage Usage Alert"
    message["From"] = sender
    message["To"] = user["email"]

    message.set_content(f"""
Hello {user['username']},

Your UMKC LMS Demo storage usage has reached
{summary['usage_percent']}%.

Storage information:

Storage used: {used_gb:.2f} GB
Storage limit: {quota_gb:.2f} GB
Remaining storage: {remaining_gb:.2f} GB

Please review your files and remove unnecessary files
to free up storage.

This is an automatic notification from UMKC LMS Demo.

Regards,
Professor / NAS Administrator
""")

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(
                mail_server,
                mail_port,
                timeout=20
            ) as server:
                server.login(mail_username, mail_password)
                server.send_message(message)

        else:
            with smtplib.SMTP(
                mail_server,
                mail_port,
                timeout=20
            ) as server:

                server.ehlo()

                if use_tls:
                    server.starttls()
                    server.ehlo()

                server.login(mail_username, mail_password)
                server.send_message(message)

        logger.info(
            "Storage alert email sent to student %s",
            user["username"]
        )

        return True

    except Exception:
        logger.exception(
            "Could not send storage alert email to %s",
            user["username"]
        )
        return False


# ==========================================================
# 12. CHECK THE 90% THRESHOLD
# ==========================================================

def check_storage_email_alert(username):
    user = get_user_information(username)

    if not user or user["role"] == "admin":
        return

    summary = get_user_storage_summary(username)

    if not summary:
        return

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            INSERT IGNORE INTO storage_alert_states (user_id, above_90)
            VALUES (%s, 0)
        """, (user["id"],))

        connection.commit()

        cursor.execute("""
            SELECT above_90
            FROM storage_alert_states
            WHERE user_id = %s
        """, (user["id"],))

        state = cursor.fetchone()
        already_alerted = bool(state["above_90"])

        if summary["usage_percent"] < ALERT_THRESHOLD:

            cursor.execute("""
                UPDATE storage_alert_states
                SET above_90 = 0
                WHERE user_id = %s
            """, (user["id"],))

            connection.commit()
            return

        if already_alerted:
            return

        # Email is sent to the student, not the professor.
        email_sent = send_student_storage_email(user, summary)

        if email_sent:
            cursor.execute("""
                UPDATE storage_alert_states
                SET above_90 = 1,
                    last_alert_at = NOW()
                WHERE user_id = %s
            """, (user["id"],))

            connection.commit()

    except Exception:
        connection.rollback()
        logger.exception("Storage threshold check failed.")

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 13. SET A STUDENT STORAGE QUOTA (ADMIN ONLY ROUTE CALLS THIS)
# ==========================================================

def set_user_quota(user_id, quota_gb):
    try:
        quota_gb = float(quota_gb)
    except (TypeError, ValueError):
        return False, "Invalid storage quota."

    if quota_gb < 0.1 or quota_gb > 1000:
        return False, "Quota must be between 0.1 and 1000 GB."

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT id, role
            FROM users
            WHERE id = %s
        """, (user_id,))

        user = cursor.fetchone()

        if not user:
            return False, "Student not found."

        if user[1] == "admin":
            return False, "Professor accounts do not use student quotas."

        quota_bytes = int(quota_gb * (1024 ** 3))

        cursor.execute("""
            INSERT INTO storage_user_quotas (user_id, quota_bytes)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE quota_bytes = VALUES(quota_bytes)
        """, (user_id, quota_bytes))

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    return True, "Student storage quota updated successfully."


# ==========================================================
# 14. ADMIN STORAGE DASHBOARD DATA
# ==========================================================

def get_admin_storage_data():

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                u.id,
                u.username,
                u.email,
                u.is_active,
                COALESCE(SUM(
                    CASE
                        WHEN f.is_deleted = 0 THEN f.size_bytes
                        ELSE 0
                    END
                ), 0) AS used_bytes
            FROM users u
            LEFT JOIN storage_file_records f
                ON f.owner_user_id = u.id
            WHERE u.role <> 'admin'
            GROUP BY
                u.id,
                u.username,
                u.email,
                u.is_active
            ORDER BY u.username
        """)

        students = cursor.fetchall()

        for student in students:

            cursor.execute("""
                INSERT IGNORE INTO storage_user_quotas
                    (user_id, quota_bytes)
                VALUES (%s, %s)
            """, (
                student["id"],
                DEFAULT_QUOTA_BYTES
            ))

        connection.commit()

        for student in students:

            cursor.execute("""
                SELECT quota_bytes
                FROM storage_user_quotas
                WHERE user_id = %s
            """, (student["id"],))

            quota = cursor.fetchone()
            quota_bytes = int(quota["quota_bytes"])

            used = int(student["used_bytes"])
            remaining = max(quota_bytes - used, 0)

            student["quota_bytes"] = quota_bytes
            student["remaining_bytes"] = remaining

            student["usage_percent"] = (
                round((used / quota_bytes) * 100, 2)
                if quota_bytes else 0
            )

        cursor.execute("""
            SELECT
                actor_username,
                action,
                relative_path,
                filename,
                file_size_bytes,
                details,
                created_at
            FROM storage_activity_logs
            ORDER BY id DESC
            LIMIT 300
        """)

        activities = cursor.fetchall()

    finally:
        cursor.close()
        connection.close()

    disk = __import__("shutil").disk_usage(STORAGE_FOLDER)

    return {
        "students": students,
        "activities": activities,
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "disk_free_bytes": disk.free
    }


# ==========================================================
# 15. STUDENT PERSONAL STORAGE AND ACTIVITY
# ==========================================================

def get_student_storage_data(username):

    summary = get_user_storage_summary(username)

    if not summary or summary["is_admin"]:
        return None

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                filename,
                relative_path,
                size_bytes,
                uploaded_at
            FROM storage_file_records
            WHERE owner_user_id = %s
              AND is_deleted = 0
            ORDER BY uploaded_at DESC
        """, (summary["user_id"],))

        files = cursor.fetchall()

        cursor.execute("""
            SELECT
                action,
                filename,
                relative_path,
                file_size_bytes,
                details,
                created_at
            FROM storage_activity_logs
            WHERE actor_user_id = %s
            ORDER BY id DESC
            LIMIT 200
        """, (summary["user_id"],))

        activities = cursor.fetchall()

    finally:
        cursor.close()
        connection.close()

    return {
        "summary": summary,
        "files": files,
        "activities": activities
    }
