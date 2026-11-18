
import os
import uuid
import shutil
import logging

from pathlib import Path
from datetime import datetime, timedelta

from database import get_db_connection
from modules.file_manager import STORAGE_FOLDER, _safe_path
from modules.storage_audit import get_user_information


logger = logging.getLogger(__name__)

# Hidden recycle folder inside NAS storage.
# It will not appear in normal student file listings.
RECYCLE_FOLDER = os.path.join(
    STORAGE_FOLDER,
    ".recycle_bin"
)

RETENTION_DAYS = 30


# ==========================================================
# 1. INITIALIZE RECYCLE BIN
# ==========================================================

def init_recycle_bin():

    os.makedirs(RECYCLE_FOLDER, exist_ok=True)

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recycle_bin_items (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,

                owner_user_id INT NOT NULL,
                deleted_by_user_id INT NOT NULL,

                original_path VARCHAR(1024) NOT NULL,
                trash_path VARCHAR(1024) NOT NULL,

                item_name VARCHAR(255) NOT NULL,

                item_type ENUM('file', 'folder') NOT NULL,

                size_bytes BIGINT NOT NULL DEFAULT 0,

                deleted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

                expires_at DATETIME NOT NULL,

                status ENUM(
                    'in_bin',
                    'restored',
                    'permanently_deleted'
                ) NOT NULL DEFAULT 'in_bin',

                INDEX idx_recycle_owner (
                    owner_user_id,
                    status
                ),

                INDEX idx_recycle_expiry (
                    expires_at,
                    status
                )

            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        connection.commit()

        logger.info("Recycle Bin database initialized.")

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 2. GET ITEM SIZE
# ==========================================================

def calculate_item_size(path):

    total = 0

    if os.path.isfile(path):
        return os.path.getsize(path)

    if os.path.isdir(path):

        for root, dirs, files in os.walk(
            path,
            followlinks=False
        ):

            dirs[:] = [
                d for d in dirs
                if not os.path.islink(os.path.join(root, d))
            ]

            for filename in files:

                file_path = os.path.join(root, filename)

                if os.path.islink(file_path):
                    continue

                try:
                    total += os.path.getsize(file_path)
                except OSError:
                    continue

    return total


# ==========================================================
# 3. RECORD ACTIVITY
# ==========================================================

def _record_recycle_activity(
    cursor,
    user,
    action,
    original_path,
    item_size,
    details
):

    cursor.execute("""
        INSERT INTO storage_activity_logs (
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
        original_path,
        Path(original_path).name,
        item_size,
        details
    ))


# ==========================================================
# 4. MOVE FILE OR FOLDER INTO RECYCLE BIN
# ==========================================================

def move_to_recycle_bin(username, relative_path):

    user = get_user_information(username)

    if not user or not user["id"]:
        return False, "User account not found."

    try:
        source_path, normalized_path = _safe_path(relative_path)

        if not normalized_path:
            return False, "Cannot delete main NAS storage."

        if (
            normalized_path == ".recycle_bin"
            or normalized_path.startswith(".recycle_bin/")
        ):
            return False, "Invalid recycle-bin operation."

        if not os.path.lexists(source_path):
            return False, "File or folder not found."

        if os.path.islink(source_path):
            return False, "Symbolic links cannot be deleted."

        item_type = (
            "folder"
            if os.path.isdir(source_path)
            else "file"
        )

        if item_type == "folder":
            if user["role"] != "admin":
                return False, "Only the Professor can delete folders."

        item_size = calculate_item_size(source_path)

        item_name = Path(normalized_path).name

        # Keep the original file owner when ownership is known.
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        moved_path = None

        try:

            if item_type == "file":

                cursor.execute("""
                    SELECT owner_user_id
                    FROM storage_file_records
                    WHERE relative_path = %s
                      AND is_deleted = 0
                    ORDER BY id DESC
                    LIMIT 1
                """, (normalized_path,))

                record = cursor.fetchone()

                owner_user_id = (
                    record["owner_user_id"]
                    if record
                    else user["id"]
                )

            else:
                # Folder deletion is Professor-only.
                # The admin becomes the recycle item owner.
                owner_user_id = user["id"]

            trash_id = uuid.uuid4().hex

            trash_relative_path = (
                ".recycle_bin/" + trash_id
            )

            trash_destination = os.path.join(
                STORAGE_FOLDER,
                ".recycle_bin",
                trash_id
            )

            # Ensure the recycle directory exists.
            os.makedirs(
                RECYCLE_FOLDER,
                exist_ok=True
            )

            # Move the actual content first.
            # It remains on the same storage filesystem.
            shutil.move(
                source_path,
                trash_destination
            )

            moved_path = trash_destination

            expires_at = (
                datetime.now() +
                timedelta(days=RETENTION_DAYS)
            )

            cursor.execute("""
                INSERT INTO recycle_bin_items (
                    owner_user_id,
                    deleted_by_user_id,
                    original_path,
                    trash_path,
                    item_name,
                    item_type,
                    size_bytes,
                    expires_at,
                    status
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, 'in_bin'
                )
            """, (
                owner_user_id,
                user["id"],
                normalized_path,
                trash_relative_path,
                item_name,
                item_type,
                item_size,
                expires_at
            ))

            # Mark file ownership records as deleted.
            if item_type == "file":

                cursor.execute("""
                    UPDATE storage_file_records
                    SET is_deleted = 1,
                        deleted_at = NOW(),
                        deleted_by_user_id = %s
                    WHERE relative_path = %s
                      AND is_deleted = 0
                """, (
                    user["id"],
                    normalized_path
                ))

            else:

                prefix = normalized_path.rstrip("/") + "/"

                cursor.execute("""
                    UPDATE storage_file_records
                    SET is_deleted = 1,
                        deleted_at = NOW(),
                        deleted_by_user_id = %s
                    WHERE is_deleted = 0
                      AND (
                            relative_path = %s
                            OR LEFT(relative_path, LENGTH(%s)) = %s
                      )
                """, (
                    user["id"],
                    normalized_path,
                    prefix,
                    prefix
                ))

            _record_recycle_activity(
                cursor,
                user,
                "delete",
                normalized_path,
                item_size,
                "Moved to Recycle Bin."
            )

            connection.commit()

            logger.info(
                "%s moved to Recycle Bin by %s",
                normalized_path,
                username
            )

            return True, (
                f"'{item_name}' moved to Recycle Bin."
            )

        except Exception:

            connection.rollback()

            # If database update fails, put the item back.
            if moved_path and os.path.lexists(moved_path):

                os.makedirs(
                    os.path.dirname(source_path),
                    exist_ok=True
                )

                if not os.path.lexists(source_path):

                    shutil.move(
                        moved_path,
                        source_path
                    )

            raise

        finally:
            cursor.close()
            connection.close()

    except Exception:

        logger.exception("Recycle Bin deletion failed.")

        return False, (
            "Unable to move item to Recycle Bin."
        )


# ==========================================================
# 5. LIST RECYCLE BIN ITEMS
# ==========================================================

def get_recycle_bin_items(username):

    user = get_user_information(username)

    if not user:
        return []

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        if user["role"] == "admin":

            cursor.execute("""
                SELECT
                    r.id,
                    r.owner_user_id,
                    r.deleted_by_user_id,
                    r.original_path,
                    r.item_name,
                    r.item_type,
                    r.size_bytes,
                    r.deleted_at,
                    r.expires_at,
                    owner.username AS owner_username,
                    deleter.username AS deleted_by_username

                FROM recycle_bin_items r

                JOIN users owner
                    ON owner.id = r.owner_user_id

                JOIN users deleter
                    ON deleter.id = r.deleted_by_user_id

                WHERE r.status = 'in_bin'

                ORDER BY r.deleted_at DESC
            """)

        else:

            cursor.execute("""
                SELECT
                    r.id,
                    r.owner_user_id,
                    r.deleted_by_user_id,
                    r.original_path,
                    r.item_name,
                    r.item_type,
                    r.size_bytes,
                    r.deleted_at,
                    r.expires_at,
                    owner.username AS owner_username,
                    deleter.username AS deleted_by_username

                FROM recycle_bin_items r

                JOIN users owner
                    ON owner.id = r.owner_user_id

                JOIN users deleter
                    ON deleter.id = r.deleted_by_user_id

                WHERE r.status = 'in_bin'
                  AND r.owner_user_id = %s

                ORDER BY r.deleted_at DESC
            """, (user["id"],))

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 6. RESTORE A RECYCLE BIN ITEM
# ==========================================================

def restore_from_recycle_bin(username, item_id):

    user = get_user_information(username)

    if not user:
        return False, "User account not found."

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT *
            FROM recycle_bin_items
            WHERE id = %s
              AND status = 'in_bin'
            FOR UPDATE
        """, (item_id,))

        item = cursor.fetchone()

        if not item:
            return False, "Recycle Bin item not found."

        # Students may restore only their own items.
        if (
            user["role"] != "admin"
            and item["owner_user_id"] != user["id"]
        ):
            return False, "You cannot restore this item."

        if item["expires_at"] <= datetime.now():
            return False, (
                "This item has expired and must be permanently deleted."
            )

        original_path, normalized_path = _safe_path(
            item["original_path"]
        )

        trash_path, _ = _safe_path(item["trash_path"])

        # Check original parent directory.
        parent = os.path.dirname(original_path)

        if not os.path.isdir(parent):
            return False, (
                "Original folder does not exist. "
                "Restore its parent folder first."
            )

        # Never overwrite an existing file or folder.
        if os.path.lexists(original_path):
            return False, (
                "A file or folder with that name already exists. "
                "Rename or move it before restoring."
            )

        if not os.path.lexists(trash_path):
            return False, "Stored recycle-bin content is missing."

        if os.path.islink(trash_path):
            return False, "Unsafe symbolic link detected."

        # Move data back to its original location.
        shutil.move(
            trash_path,
            original_path
        )

        try:

            cursor.execute("""
                UPDATE recycle_bin_items
                SET status = 'restored'
                WHERE id = %s
            """, (item_id,))

            # Restore ownership records for files or folders.
            if item["item_type"] == "file":

                cursor.execute("""
                    UPDATE storage_file_records
                    SET is_deleted = 0,
                        deleted_at = NULL,
                        deleted_by_user_id = NULL
                    WHERE relative_path = %s
                """, (normalized_path,))

            else:

                prefix = normalized_path.rstrip("/") + "/"

                cursor.execute("""
                    UPDATE storage_file_records
                    SET is_deleted = 0,
                        deleted_at = NULL,
                        deleted_by_user_id = NULL
                    WHERE relative_path = %s
                       OR LEFT(relative_path, LENGTH(%s)) = %s
                """, (
                    normalized_path,
                    prefix,
                    prefix
                ))

            _record_recycle_activity(
                cursor,
                user,
                "restore",
                normalized_path,
                item["size_bytes"],
                "Restored from Recycle Bin."
            )

            connection.commit()

        except Exception:

            connection.rollback()

            # Move the file back into the recycle folder.
            if os.path.lexists(original_path):

                os.makedirs(
                    os.path.dirname(trash_path),
                    exist_ok=True
                )

                if not os.path.lexists(trash_path):

                    shutil.move(
                        original_path,
                        trash_path
                    )

            raise

        return True, (
            f"'{item['item_name']}' restored successfully."
        )

    except Exception:

        logger.exception("Recycle Bin restore failed.")

        return False, "Unable to restore this item."

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 7. PERMANENTLY DELETE AN ITEM
# ==========================================================

def permanently_delete_item(username, item_id):

    user = get_user_information(username)

    if not user:
        return False, "User account not found."

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT *
            FROM recycle_bin_items
            WHERE id = %s
              AND status = 'in_bin'
            FOR UPDATE
        """, (item_id,))

        item = cursor.fetchone()

        if not item:
            return False, "Recycle Bin item not found."

        if (
            user["role"] != "admin"
            and item["owner_user_id"] != user["id"]
        ):
            return False, "You cannot permanently delete this item."

        trash_path, _ = _safe_path(item["trash_path"])

        if os.path.islink(trash_path):
            return False, "Unsafe symbolic link detected."

        if os.path.isdir(trash_path):
            shutil.rmtree(trash_path)

        elif os.path.isfile(trash_path):
            os.remove(trash_path)

        else:
            return False, "Recycle Bin content not found."

        cursor.execute("""
            UPDATE recycle_bin_items
            SET status = 'permanently_deleted'
            WHERE id = %s
        """, (item_id,))

        _record_recycle_activity(
            cursor,
            user,
            "permanent_delete",
            item["original_path"],
            item["size_bytes"],
            "Permanently deleted from Recycle Bin."
        )

        connection.commit()

        return True, (
            f"'{item['item_name']}' permanently deleted."
        )

    except Exception:

        connection.rollback()

        logger.exception("Permanent deletion failed.")

        return False, "Unable to permanently delete item."

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# 8. AUTOMATIC 30-DAY CLEANUP
# ==========================================================

def cleanup_expired_items():

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    deleted_count = 0

    try:

        cursor.execute("""
            SELECT *
            FROM recycle_bin_items
            WHERE status = 'in_bin'
              AND expires_at <= NOW()
            ORDER BY id
            FOR UPDATE
        """)

        expired_items = cursor.fetchall()

        for item in expired_items:

            trash_path, _ = _safe_path(item["trash_path"])

            if os.path.islink(trash_path):
                logger.error(
                    "Skipped unsafe recycle path: %s",
                    trash_path
                )
                continue

            if os.path.isdir(trash_path):

                shutil.rmtree(trash_path)

            elif os.path.isfile(trash_path):

                os.remove(trash_path)

            cursor.execute("""
                UPDATE recycle_bin_items
                SET status = 'permanently_deleted'
                WHERE id = %s
            """, (item["id"],))

            deleted_count += 1

        connection.commit()

        if deleted_count:
            logger.info(
                "Automatic Recycle Bin cleanup removed %s expired items.",
                deleted_count
            )

        return deleted_count

    except Exception:

        connection.rollback()

        logger.exception(
            "Automatic Recycle Bin cleanup failed."
        )

        raise

    finally:
        cursor.close()
        connection.close()
