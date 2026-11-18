from pathlib import Path
from datetime import datetime
import tarfile
import shutil
import tempfile
from pathlib import PurePosixPath
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def safe_backup_filter(tar_info):
    """Exculde symbolic and hard links from backups."""
    if tar_info.issym() or tar_info.islnk():
        return None
    return tar_info 
def create_backup():
    """Create a timestamped compressed backup of NAS storage."""
    if not STORAGE_DIR.is_dir():
        return False, "NAS storage folder was not found."
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"nas_storage_{timestamp}.tar.gz"
    backup_path = BACKUP_DIR / filename
    temporary_path = BACKUP_DIR / f"{filename}.tmp"
    try:
        with tarfile.open(temporary_path, "w:gz") as archive:
            archive.add(
                STORAGE_DIR,
                arcname="storage",
                filter=safe_backup_filter
            )
        temporary_path.replace(backup_path)
        return True, filename
    except (OSError, tarfile.TarError) as error:
        temporary_path.unlink(missing_ok=True)
        return False, str(error)

def list_backups():
    """Return available NAS backup archives."""
    backups = []
    for backup in BACKUP_DIR.glob("nas_storage_*.tar.gz"):
        if backup.is_symlink() or not backup.is_file():
            continue
        backups.append({
            "name": backup.name,
            "size_kb": round(backup.stat().st_size / 1024, 2),
            "created_at": datetime.fromtimestamp(
                backup.stat().st_mtime
            ).strftime("%Y-%m-%d %H:%M:%S")
        })
    return sorted(
        backups,
        key=lambda item: item["created_at"],
        reverse=True
    )

def delete_backup(filename):
    """Delete one backup archive safely."""
    if not isinstance(filename, str):
         return False, "Invalid backup filename."
    if Path(filename).name != filename:
        return False, "Invalid backup filename."
    if not filename.startswith("nas_storage_") or not filename.endswith(".tar.gz"):
        return False, "Invalid backup filename."
    backup_path = BACKUP_DIR / filename
    try:
        if backup_path.is_symlink() or not backup_path.is_file():
            return False, "Backup file was not found."
        backup_path.unlink()
        return True, "Backup deleted successfully."
    except ODSError as error:
        return False, str(error)

def restore_backup(filename):
    """safely merge files from a NAS backup into storage."""
    if not isinstance(filename, str):
        return False, "Invalid backup filename."
    if (Path(filename).name != filename
             or not filename.startswith("nas_storage_")
             or not filename.endswith("tar.gz")):
        return False, "Invalid backup filename."
    backup_path = BACKUP_DIR /filename
    if backup_path.is_symlink() or not backup_path.is_file():
        return false, "Backup file was not found."
    try:
        storage_root = STORAGE_DIR.resolve()
        with tarfile.open(backup_path, "r:gz") as archive:
            members = archive.getmembers()
            prepared = []
            seen = set()
            root_found = False
            for member in members:
                name = member.name
                parts = PurePosixPath(name).parts
                if("\\" in name or not parts
                       or PurePosixPath(name).is_absolute()
                       or parts[0] != "storage"
                       or ".." in parts):
                   raise ValueError("Unsafe archive path.")
                if (member.issym() or member.islnk()
                        or member.isdev() or member.isfifo()):
                    raise ValueError("Link and special files are not allowed.")
                if len(parts) == 1:
                    if not member.isdir():
                        raise ValueError("Invalid storage archive.")
                    root_found = True
                    continue
                if not (member.isdir() or member.isfile()):
                    raise ValueError("Unsupported archive entry.")
                relative = Path(*parts[1:])
                if relative in seen:
                    raise ValueError("Duplicate archive path.")
                seen.add(relative)
                prepared.append((member, relative))
            if not root_found:
                raise ValueError("Storage folder missing from backup.")
            with tempfile.TemporaryDirectory(
                prefix=".restore_",
                dir=BACKUP_DIR
            ) as temporary_dir:
                staging = Path(temporary_dir) / "storage"
                staging.mkdir()
                for member, relative in prepared:
                    target = staging / relative
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(
                            parents=True, exist_ok=True
                        )
                        source = archive.extractfile(member)
                        if source is None:
                            raise ValueError("Unable to read archive file.")
                        with source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
                for item in sorted(
                    staging.rglob("*"),
                    key=lambda p: len(p.relative_to(staging).parts)
                ):
                    relative = item.relative_to(staging)
                    destination = STORAGE_DIR / relative
                    current = STORAGE_DIR
                    for part in relative.parts:
                        current = current / part
                        if current.is_symlink():
                            raise ValueError(
                                "Restore blocked by a symbolic link."
                            )
                        current.resolve(strict=False).relative_to(
                            storage_root
                        )
                        if item.is_dir():
                            destination.mkdir(
                                parents=True, exist_ok=True
                            )
                        else:
                            destination.parent.mkdir(
                                 parents=True, exist_ok=True            
                            )
                            if destination.exists() and destination.is_dir():
                                raise ValueError(
                                    "A folder conflicts with a backup file."
                                )
                            shutil.copy2(item, destination)
        return True, (
            "Backup restored successfully. "
            "Existing matching files were replaced; "
            "other files were retained."
        )
    except (OSError, tarfile.TarError, ValueError) as error:                      
        return False, f"Restore failed: {error}"
