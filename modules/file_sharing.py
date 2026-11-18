
from database import get_db_connection


# ==========================================================
# 1. CREATE FILE-SHARING TABLE
# ==========================================================

def init_file_sharing_tables():

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_shares (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                file_record_id BIGINT NOT NULL,
                owner_user_id INT NOT NULL,
                shared_with_user_id INT NOT NULL,
                permission ENUM('read', 'edit') NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

                UNIQUE KEY unique_file_recipient (
                    file_record_id,
                    shared_with_user_id
                ),

                INDEX idx_share_owner (owner_user_id),
                INDEX idx_share_recipient (shared_with_user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        connection.commit()
        print("File-sharing table created successfully.")

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 2. GET USER
# ==========================================================

def get_user(username):

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, username, email, role, is_active
            FROM users
            WHERE username = %s
        """, (username,))

        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 3. FIND THE ACTIVE FILE RECORD
# ==========================================================

def get_file_record(relative_path):

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, owner_user_id, relative_path,
                   filename, size_bytes
            FROM storage_file_records
            WHERE relative_path = %s
              AND is_deleted = 0
            ORDER BY id DESC
            LIMIT 1
        """, (relative_path,))

        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 4. CHECK FILE ACCESS
# ==========================================================

def can_access_file(username, relative_path, required="read"):
    """
    Check whether a user can read or edit a file.

    Admin can access all files.
    Owner can access their own files.
    Shared users receive read or edit permission.
    """

    if required not in ("read", "edit"):
        return False

    user = get_user(username)

    if not user or not user["is_active"]:
        return False

    if user["role"] == "admin":
        return True

    file_record = get_file_record(relative_path)

    if not file_record:
        return False

    if file_record["owner_user_id"] == user["id"]:
        return True

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT permission
            FROM file_shares
            WHERE file_record_id = %s
              AND shared_with_user_id = %s
        """, (
            file_record["id"],
            user["id"]
        ))

        share = cursor.fetchone()

        if not share:
            return False

        if required == "read":
            return share["permission"] in ("read", "edit")

        return share["permission"] == "edit"

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 5. SHARE A FILE WITH ANOTHER USER
# ==========================================================

def share_file(
    owner_username,
    relative_path,
    recipient_username,
    permission
):
    """Share an individual file with a registered user."""

    permission = (permission or "").strip().lower()

    if permission not in ("read", "edit"):
        return False, "Choose Read or Edit permission."

    if owner_username == recipient_username:
        return False, "You cannot share a file with yourself."

    owner = get_user(owner_username)
    recipient = get_user(recipient_username)

    if not owner or not owner["is_active"]:
        return False, "Owner account not found or inactive."

    if not recipient or not recipient["is_active"]:
        return False, "Recipient account not found or inactive."

    if recipient["role"] == "admin":
        return False, "Select a student account."

    file_record = get_file_record(relative_path)

    if not file_record:
        return False, "File ownership record not found."

    # Only the file owner can share their file.
    # Admin access remains available for oversight.
    if (
        owner["role"] != "admin"
        and file_record["owner_user_id"] != owner["id"]
    ):
        return False, "Only the file owner can share this file."

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO file_shares (
                file_record_id,
                owner_user_id,
                shared_with_user_id,
                permission
            )
            VALUES (%s, %s, %s, %s)

            ON DUPLICATE KEY UPDATE
                permission = VALUES(permission),
                owner_user_id = VALUES(owner_user_id)
        """, (
            file_record["id"],
            file_record["owner_user_id"],
            recipient["id"],
            permission
        ))

        connection.commit()

        return True, (
            f"File shared with {recipient_username} "
            f"with {permission.title()} permission."
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 6. LIST USERS WHO HAVE ACCESS TO A FILE
# ==========================================================

def get_file_shares(owner_username, relative_path):

    owner = get_user(owner_username)

    if not owner:
        return []

    file_record = get_file_record(relative_path)

    if not file_record:
        return []

    if (
        owner["role"] != "admin"
        and file_record["owner_user_id"] != owner["id"]
    ):
        return []

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                fs.id AS share_id,
                u.username,
                u.email,
                fs.permission,
                fs.created_at
            FROM file_shares fs

            JOIN users u
                ON u.id = fs.shared_with_user_id

            WHERE fs.file_record_id = %s

            ORDER BY u.username
        """, (file_record["id"],))

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 7. REVOKE ACCESS TO A FILE
# ==========================================================

def revoke_file_access(actor_username, share_id):

    actor = get_user(actor_username)

    if not actor:
        return False, "Account not found."

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                fs.id,
                fs.owner_user_id,
                u.username
            FROM file_shares fs

            JOIN users u
                ON u.id = fs.shared_with_user_id

            WHERE fs.id = %s
        """, (share_id,))

        share = cursor.fetchone()

        if not share:
            return False, "Sharing record not found."

        if (
            actor["role"] != "admin"
            and actor["id"] != share["owner_user_id"]
        ):
            return False, "Only the owner or Professor can revoke access."

        cursor.execute("""
            DELETE FROM file_shares
            WHERE id = %s
        """, (share_id,))

        connection.commit()

        return True, (
            f"Access revoked for {share['username']}."
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 8. FILTER FILE LISTING FOR EACH USER
# ==========================================================

def filter_accessible_items(username, items, current_path=""):

    user = get_user(username)

    if not user:
        return []

    # Professor/Admin can see all NAS files.
    if user["role"] == "admin":
        return items

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT DISTINCT f.relative_path

            FROM storage_file_records f

            LEFT JOIN file_shares s
                ON s.file_record_id = f.id
               AND s.shared_with_user_id = %s

            WHERE f.is_deleted = 0
              AND (
                    f.owner_user_id = %s
                    OR s.id IS NOT NULL
              )
        """, (user["id"], user["id"]))

        accessible_paths = {
            row["relative_path"]
            for row in cursor.fetchall()
        }

    finally:
        cursor.close()
        connection.close()

    visible_items = []

    for item in items:

        item_path = item["path"]

        if not item["is_dir"]:

            if item_path in accessible_paths:
                visible_items.append(item)

        else:

            folder_prefix = item_path.rstrip("/") + "/"

            if any(
                path.startswith(folder_prefix)
                for path in accessible_paths
            ):
                visible_items.append(item)

    return visible_items
