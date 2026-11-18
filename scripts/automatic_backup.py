
#!/usr/bin/env python3

import os
import sys
import json
import time
import shutil
import hashlib
import logging
import subprocess
import tarfile
import tempfile

from pathlib import Path
from datetime import datetime, timedelta


# ==========================================================
# NAS AUTOMATIC BACKUP CONFIGURATION
# ==========================================================

HOME = Path.home()
PROJECT = HOME / "NAS-Management-System"

STORAGE_DIR = PROJECT / "storage"
LOCAL_BACKUP_DIR = PROJECT / "backups" / "automatic"
LOG_DIR = PROJECT / "logs"

DROPBOX_DIR = Path("/media/sf_NAS_Backups")

DATABASE_NAME = "nas_management"
MYSQL_CREDENTIALS = HOME / ".my.cnf"

RETENTION_DAYS = 30

LOG_FILE = LOG_DIR / "automatic_backup.log"


# ==========================================================
# LOGGING
# ==========================================================

LOG_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("NAS_BACKUP")


# ==========================================================
# FILE HASH
# ==========================================================

def sha256_file(path):

    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


# ==========================================================
# CHECK SYSTEM REQUIREMENTS
# ==========================================================

def check_requirements():

    if not STORAGE_DIR.is_dir():
        raise RuntimeError(
            f"NAS storage folder not found: {STORAGE_DIR}"
        )

    if not MYSQL_CREDENTIALS.is_file():
        raise RuntimeError(
            "MySQL credentials file ~/.my.cnf is missing"
        )

    if not shutil.which("mysqldump"):
        raise RuntimeError("mysqldump is not installed")

    if not shutil.which("mountpoint"):
        raise RuntimeError("mountpoint command is unavailable")

    result = subprocess.run(
        ["mountpoint", "-q", str(DROPBOX_DIR)],
        check=False
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Dropbox shared folder is not mounted. "
            "Expected: /media/sf_NAS_Backups"
        )

    if not DROPBOX_DIR.is_dir():
        raise RuntimeError("Dropbox backup folder is unavailable")

    # Test that the service can write to Dropbox.
    test_file = DROPBOX_DIR / ".nas_backup_test"

    try:
        with test_file.open("w", encoding="utf-8") as file:
            file.write("NAS backup connection test")

        test_file.unlink()

    except OSError as error:
        raise RuntimeError(
            f"Cannot write to Dropbox folder: {error}"
        ) from error

    logger.info("All backup prerequisites passed")


# ==========================================================
# MYSQL DATABASE BACKUP
# ==========================================================

def create_database_dump(output_file):

    command = [
        "mysqldump",
        f"--defaults-extra-file={MYSQL_CREDENTIALS}",
        "--single-transaction",
        "--quick",
        "--hex-blob",
        "--databases",
        DATABASE_NAME
    ]

    with output_file.open("wb") as output:

        result = subprocess.run(
            command,
            stdout=output,
            stderr=subprocess.PIPE,
            check=False
        )

    if result.returncode != 0:

        error_message = result.stderr.decode(
            "utf-8", errors="replace"
        )

        raise RuntimeError(
            f"MySQL database backup failed: {error_message}"
        )

    if output_file.stat().st_size == 0:
        raise RuntimeError("MySQL database dump is empty")

    logger.info("MySQL database backup created successfully")


# ==========================================================
# AVOID BACKING UP SPECIAL FILES AND SYMLINKS
# ==========================================================

def safe_tar_filter(member):

    if (
        member.issym()
        or member.islnk()
        or member.isdev()
        or member.isfifo()
    ):
        logger.warning(
            "Skipped unsupported filesystem entry: %s",
            member.name
        )
        return None

    return member


# ==========================================================
# CREATE BACKUP ARCHIVE
# ==========================================================

def create_archive():

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    archive_name = f"NAS_auto_{timestamp}.tar.gz"

    archive_path = LOCAL_BACKUP_DIR / archive_name

    temporary_archive = (
        LOCAL_BACKUP_DIR / f".{archive_name}.partial"
    )

    try:

        with tempfile.TemporaryDirectory(
            prefix="nas_database_backup_"
        ) as temporary_directory:

            temp_dir = Path(temporary_directory)

            database_file = temp_dir / "nas_management.sql"
            manifest_file = temp_dir / "manifest.json"

            # Create database dump.
            create_database_dump(database_file)

            # Calculate uploaded file statistics.
            file_count = 0
            total_bytes = 0

            for item in STORAGE_DIR.rglob("*"):

                if item.is_symlink():
                    continue

                if item.is_file():
                    file_count += 1
                    total_bytes += item.stat().st_size

            manifest = {
                "backup_name": archive_name,
                "created_at": datetime.now().astimezone().isoformat(),
                "database": DATABASE_NAME,
                "storage_folder": "storage",
                "file_count": file_count,
                "storage_bytes": total_bytes,
                "retention_days": RETENTION_DAYS
            }

            manifest_file.write_text(
                json.dumps(manifest, indent=4),
                encoding="utf-8"
            )

            # Create archive.
            with tarfile.open(
                temporary_archive,
                mode="w:gz",
                compresslevel=6
            ) as archive:

                archive.add(
                    STORAGE_DIR,
                    arcname="storage",
                    recursive=True,
                    filter=safe_tar_filter
                )

                archive.add(
                    database_file,
                    arcname="database/nas_management.sql"
                )

                archive.add(
                    manifest_file,
                    arcname="manifest.json"
                )

        # Verify the archive.
        with tarfile.open(
            temporary_archive,
            mode="r:gz"
        ) as archive:

            members = archive.getmembers()

            member_names = {
                member.name for member in members
            }

            if "database/nas_management.sql" not in member_names:
                raise RuntimeError(
                    "Database dump missing from archive"
                )

            for member in members:

                name = Path(member.name)

                if name.is_absolute() or ".." in name.parts:
                    raise RuntimeError(
                        "Unsafe path detected in backup archive"
                    )

                if member.issym() or member.islnk():
                    raise RuntimeError(
                        "Unexpected link found in archive"
                    )

        os.replace(temporary_archive, archive_path)

        logger.info(
            "Backup archive created: %s",
            archive_path
        )

        return archive_path

    except Exception:

        temporary_archive.unlink(missing_ok=True)
        raise


# ==========================================================
# COPY TO WINDOWS DROPBOX FOLDER
# ==========================================================

def copy_to_dropbox(archive_path):

    destination = DROPBOX_DIR / archive_path.name

    temporary_destination = (
        DROPBOX_DIR / f".{archive_path.name}.partial"
    )

    try:

        shutil.copyfile(
            archive_path,
            temporary_destination
        )

        source_hash = sha256_file(archive_path)
        destination_hash = sha256_file(temporary_destination)

        if source_hash != destination_hash:
            raise RuntimeError(
                "Dropbox copy checksum verification failed"
            )

        os.replace(
            temporary_destination,
            destination
        )

        logger.info(
            "Verified copy saved to Dropbox folder: %s",
            destination
        )

    except Exception:

        temporary_destination.unlink(missing_ok=True)
        raise


# ==========================================================
# AUTOMATIC 30-DAY RETENTION
# ==========================================================

def remove_old_backups(folder):

    cutoff = time.time() - (
        RETENTION_DAYS * 24 * 60 * 60
    )

    for backup in folder.glob("NAS_auto_*.tar.gz"):

        try:

            if backup.is_file() and backup.stat().st_mtime < cutoff:

                backup.unlink()

                logger.info(
                    "Removed expired backup: %s",
                    backup
                )

        except OSError as error:

            logger.warning(
                "Could not remove %s: %s",
                backup,
                error
            )


# ==========================================================
# MAIN BACKUP WORKFLOW
# ==========================================================

def main():

    logger.info("======================================")
    logger.info("NAS AUTOMATIC BACKUP STARTED")

    check_requirements()

    # Local archive first.
    archive_path = create_archive()

    # Verify and copy to Dropbox.
    copy_to_dropbox(archive_path)

    # Remove old backups from both locations.
    remove_old_backups(LOCAL_BACKUP_DIR)
    remove_old_backups(DROPBOX_DIR)

    logger.info(
        "NAS AUTOMATIC BACKUP COMPLETED SUCCESSFULLY"
    )

    logger.info(
        "Local backup: %s",
        archive_path
    )

    logger.info(
        "Dropbox backup: %s",
        DROPBOX_DIR / archive_path.name
    )

    logger.info("======================================")


if __name__ == "__main__":

    try:
        main()

    except Exception:

        logger.exception(
            "NAS AUTOMATIC BACKUP FAILED"
        )

        sys.exit(1)
