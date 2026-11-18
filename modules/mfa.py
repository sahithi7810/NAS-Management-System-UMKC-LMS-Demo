
import os
import io
import base64
import secrets

import pyotp
import qrcode

from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import generate_password_hash, check_password_hash

from dotenv import load_dotenv
load_dotenv()

from database import get_db_connection


def _cipher():
    key = os.getenv("MFA_ENCRYPTION_KEY")

    if not key:
        raise RuntimeError("MFA_ENCRYPTION_KEY is missing from .env")

    return Fernet(key.encode("ascii"))


def is_mfa_enabled(username):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT mfa_enabled FROM users WHERE username = %s",
            (username,)
        )
        user = cursor.fetchone()
        return bool(user and user["mfa_enabled"])
    finally:
        cursor.close()
        connection.close()


def begin_mfa_enrollment(username):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT mfa_enabled, mfa_pending_secret
            FROM users
            WHERE username = %s
            """,
            (username,)
        )

        user = cursor.fetchone()

        if not user:
            raise ValueError("User account was not found.")

        if user["mfa_enabled"]:
            raise ValueError("MFA is already enabled.")

        if user["mfa_pending_secret"]:
            try:
                secret = _cipher().decrypt(
                    user["mfa_pending_secret"].encode()
                ).decode()
            except InvalidToken:
                raise RuntimeError(
                    "Unable to decrypt the pending MFA secret."
                )
        else:
            secret = pyotp.random_base32()
            encrypted = _cipher().encrypt(secret.encode()).decode()

            cursor.execute(
                """
                UPDATE users
                SET mfa_pending_secret = %s
                WHERE username = %s AND mfa_enabled = 0
                """,
                (encrypted, username)
            )
            connection.commit()

        uri = pyotp.TOTP(secret).provisioning_uri(
            name=username,
            issuer_name="NAS Management System"
        )

        qr = qrcode.QRCode(
            version=1,
            box_size=8,
            border=4
        )
        qr.add_data(uri)
        qr.make(fit=True)

        image = qr.make_image(fill_color="black", back_color="white")

        output = io.BytesIO()
        image.save(output, format="PNG")

        qr_data = base64.b64encode(output.getvalue()).decode()

        return secret, "data:image/png;base64," + qr_data

    finally:
        cursor.close()
        connection.close()


def confirm_mfa_enrollment(username, token):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT id, mfa_enabled, mfa_pending_secret
            FROM users
            WHERE username = %s
            """,
            (username,)
        )

        user = cursor.fetchone()

        if not user or user["mfa_enabled"] or not user["mfa_pending_secret"]:
            return False, [], "MFA enrollment was not started."

        secret = _cipher().decrypt(
            user["mfa_pending_secret"].encode()
        ).decode()

        token = (token or "").strip()

        if not token.isdigit() or len(token) != 6:
            return False, [], "Enter a valid six-digit code."

        if not pyotp.TOTP(secret).verify(token, valid_window=1):
            return False, [], "Incorrect verification code. Try again."

        recovery_codes = []

        for _ in range(10):
            raw = secrets.token_hex(4).upper()
            recovery_codes.append(raw[:4] + "-" + raw[4:])

        cursor.execute(
            """
            UPDATE users
            SET mfa_enabled = 1,
                mfa_secret = mfa_pending_secret,
                mfa_pending_secret = NULL,
                mfa_enrolled_at = UTC_TIMESTAMP()
            WHERE id = %s AND mfa_enabled = 0
            """,
            (user["id"],)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return False, [], "MFA enrollment could not be completed."

        cursor.execute(
            "DELETE FROM mfa_recovery_codes WHERE user_id = %s",
            (user["id"],)
        )

        for code in recovery_codes:
            normalized = code.replace("-", "")
            code_hash = generate_password_hash(normalized)

            cursor.execute(
                """
                INSERT INTO mfa_recovery_codes (user_id, code_hash)
                VALUES (%s, %s)
                """,
                (user["id"], code_hash)
            )

        connection.commit()

        return True, recovery_codes, "MFA enabled successfully."

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


def verify_mfa_code(username, token):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT id, mfa_enabled, mfa_secret
            FROM users
            WHERE username = %s AND is_active = 1
            """,
            (username,)
        )

        user = cursor.fetchone()

        if not user or not user["mfa_enabled"] or not user["mfa_secret"]:
            return False

        token = (token or "").strip()

        if (
            len(token) == 6
            and token.isdigit()
        ):
            secret = _cipher().decrypt(
                user["mfa_secret"].encode()
            ).decode()

            if pyotp.TOTP(secret).verify(token, valid_window=1):
                return True

        normalized = token.replace("-", "").replace(" ", "").upper()

        cursor.execute(
            """
            SELECT id, code_hash
            FROM mfa_recovery_codes
            WHERE user_id = %s AND used_at IS NULL
            FOR UPDATE
            """,
            (user["id"],)
        )

        rows = cursor.fetchall()

        for row in rows:
            if check_password_hash(row["code_hash"], normalized):
                cursor.execute(
                    """
                    UPDATE mfa_recovery_codes
                    SET used_at = UTC_TIMESTAMP()
                    WHERE id = %s AND used_at IS NULL
                    """,
                    (row["id"],)
                )

                if cursor.rowcount == 1:
                    connection.commit()
                    return True

        connection.rollback()
        return False

    finally:
        cursor.close()
        connection.close()
