
import os
import secrets
import hashlib
import smtplib
import ssl

from datetime import datetime, timedelta
from email.message import EmailMessage

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

from database import get_db_connection


RESET_EXPIRY_MINUTES = 15


def init_password_reset_table():
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                token_hash CHAR(64) NOT NULL UNIQUE,
                expires_at DATETIME NOT NULL,
                used_at DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_reset_user (user_id),
                CONSTRAINT fk_password_reset_user
                    FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB
        """)
        connection.commit()

    finally:
        cursor.close()
        connection.close()


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_reset_token(email):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, email
            FROM users
            WHERE LOWER(email) = LOWER(%s)
              AND is_active = 1
            LIMIT 1
        """, (email,))

        user = cursor.fetchone()

        if not user:
            return None

        # Limit reset requests to one per minute per account.
        cursor.execute("""
            SELECT id
            FROM password_reset_tokens
            WHERE user_id = %s
              AND created_at >=
                  DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 MINUTE)
              AND used_at IS NULL
            LIMIT 1
        """, (user["id"],))

        if cursor.fetchone():
            return None

        # Invalidate older outstanding reset links.
        cursor.execute("""
            UPDATE password_reset_tokens
            SET used_at = UTC_TIMESTAMP()
            WHERE user_id = %s AND used_at IS NULL
        """, (user["id"],))

        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)

        cursor.execute("""
            INSERT INTO password_reset_tokens
                (user_id, token_hash, expires_at)
            VALUES (
                %s,
                %s,
                DATE_ADD(UTC_TIMESTAMP(), INTERVAL 15 MINUTE)
            )
        """, (user["id"], token_hash))

        connection.commit()

        return token, user["email"]

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


def invalidate_reset_token(token):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE password_reset_tokens
            SET used_at = UTC_TIMESTAMP()
            WHERE token_hash = %s AND used_at IS NULL
        """, (_hash_token(token),))

        connection.commit()

    finally:
        cursor.close()
        connection.close()


def is_reset_token_valid(token):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id
            FROM password_reset_tokens
            WHERE token_hash = %s
              AND used_at IS NULL
              AND expires_at > UTC_TIMESTAMP()
            LIMIT 1
        """, (_hash_token(token),))

        return cursor.fetchone() is not None

    finally:
        cursor.close()
        connection.close()


def perform_password_reset(token, new_password):
    if len(new_password) < 8:
        return False

    new_hash = generate_password_hash(new_password)

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, user_id
            FROM password_reset_tokens
            WHERE token_hash = %s
              AND used_at IS NULL
              AND expires_at > UTC_TIMESTAMP()
            LIMIT 1
            FOR UPDATE
        """, (_hash_token(token),))

        record = cursor.fetchone()

        if not record:
            connection.rollback()
            return False

        cursor.execute("""
            UPDATE users
            SET password_hash = %s
            WHERE id = %s
        """, (new_hash, record["user_id"]))

        # Mark the current link and all other outstanding links used.
        cursor.execute("""
            UPDATE password_reset_tokens
            SET used_at = UTC_TIMESTAMP()
            WHERE user_id = %s AND used_at IS NULL
        """, (record["user_id"],))

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


def send_password_reset_email(recipient, reset_url):
    host = os.getenv("MAIL_SERVER", "").strip()
    port = int(os.getenv("MAIL_PORT", "587"))
    username = os.getenv("MAIL_USERNAME", "").strip()
    password = os.getenv("MAIL_PASSWORD", "")
    sender = os.getenv("MAIL_DEFAULT_SENDER", "").strip() or username

    use_tls = os.getenv("MAIL_USE_TLS", "true").lower() in (
        "true", "1", "yes"
    )
    use_ssl = os.getenv("MAIL_USE_SSL", "false").lower() in (
        "true", "1", "yes"
    )

    if not host or not sender:
        raise RuntimeError("Email server settings are missing.")

    if use_tls and use_ssl:
        raise RuntimeError("Configure either TLS or SSL, not both.")

    message = EmailMessage()
    message["Subject"] = "UMKC LMS Demo - Password Reset"
    message["From"] = sender
    message["To"] = recipient

    message.set_content(f"""
Hello,

A password reset was requested for your UMKC LMS Demo account.

Use this secure link to create a new password:

{reset_url}

This link expires in 15 minutes and can only be used once.

If you did not request this reset, you can ignore this email.

UMKC LMS Demo
Unofficial Student Project
""")

    context = ssl.create_default_context()

    if use_ssl:
        with smtplib.SMTP_SSL(
            host, port, context=context, timeout=20
        ) as server:
            if username:
                server.login(username, password)
            server.send_message(message)

    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()

            if use_tls:
                server.starttls(context=context)
                server.ehlo()

            if username:
                server.login(username, password)

            server.send_message(message)


def get_reset_csrf_token(session):
    if "password_reset_csrf" not in session:
        session["password_reset_csrf"] = secrets.token_urlsafe(32)

    return session["password_reset_csrf"]


def verify_reset_csrf_token(session, submitted_token):
    import hmac

    saved_token = session.get("password_reset_csrf", "")

    if not saved_token or not submitted_token:
        return False

    return hmac.compare_digest(saved_token, submitted_token)
