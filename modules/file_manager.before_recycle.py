
import os
from werkzeug.utils import secure_filename


# ==========================================================
# NAS STORAGE LOCATION
# ==========================================================

STORAGE_FOLDER = os.path.realpath(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "storage"
    )
)

os.makedirs(STORAGE_FOLDER, exist_ok=True)


# ==========================================================
# SAFE PATH VALIDATION
# ==========================================================

def _safe_path(relative_path=""):
    """Validate paths and prevent access outside NAS storage."""

    if not isinstance(relative_path, str):
        raise ValueError("Invalid path.")

    relative_path = relative_path.replace("\\", "/")

    if relative_path.startswith("/") or "\x00" in relative_path:
        raise ValueError("Invalid path.")

    parts = relative_path.split("/")

    if any(part == ".." for part in parts):
        raise ValueError("Invalid path.")

    parts = [part for part in parts if part not in ("", ".")]

    root = os.path.realpath(STORAGE_FOLDER)
    target = os.path.join(root, *parts)

    current = root

    for part in parts:
        current = os.path.join(current, part)

        if os.path.islink(current):
            raise ValueError("Symbolic links are not allowed.")

    target = os.path.realpath(target)

    if os.path.commonpath([root, target]) != root:
        raise ValueError("Invalid storage location.")

    return target, "/".join(parts)


# ==========================================================
# UPLOAD FILE
# ==========================================================

def upload_file(file, relative_path=""):
    """Upload a file into the selected NAS folder."""

    if not file or not file.filename:
        return False

    filename = secure_filename(file.filename)

    if not filename:
        return False

    try:
        directory, _ = _safe_path(relative_path)

        if not os.path.isdir(directory):
            return False

        destination = os.path.join(directory, filename)

        if os.path.lexists(destination):
            return False

        file.save(destination)

        return True

    except (ValueError, OSError):
        return False


# ==========================================================
# LIST FILES AND FOLDERS
# ==========================================================

def get_all_files(relative_path=""):
    """List files and folders in a NAS directory."""

    directory, current_path = _safe_path(relative_path)

    if not os.path.isdir(directory):
        raise FileNotFoundError("Folder not found.")

    items = []

    with os.scandir(directory) as entries:

        for entry in entries:

            if entry.is_symlink():
                continue

            item_path = "/".join(
                part
                for part in (current_path, entry.name)
                if part
            )

            if entry.is_dir(follow_symlinks=False):

                items.append({
                    "name": entry.name,
                    "size": "Folder",
                    "is_dir": True,
                    "path": item_path
                })

            elif entry.is_file(follow_symlinks=False):

                size_kb = round(
                    entry.stat(follow_symlinks=False).st_size / 1024,
                    2
                )

                items.append({
                    "name": entry.name,
                    "size": size_kb,
                    "is_dir": False,
                    "path": item_path
                })

    items.sort(
        key=lambda item: (
            not item["is_dir"],
            item["name"].lower()
        )
    )

    return items


# ==========================================================
# CREATE FOLDER
# ==========================================================

def create_folder(folder_name, relative_path=""):
    """Create a folder inside NAS storage."""

    folder_name = folder_name.strip()

    if (
        not folder_name
        or "/" in folder_name
        or "\\" in folder_name
        or folder_name in (".", "..")
    ):
        return False, "Invalid folder name."

    safe_name = secure_filename(folder_name)

    if not safe_name:
        return False, "Invalid folder name."

    try:

        directory, _ = _safe_path(relative_path)

        if not os.path.isdir(directory):
            return False, "Parent folder not found."

        os.mkdir(os.path.join(directory, safe_name))

        return True, (
            f"Folder '{safe_name}' created successfully."
        )

    except FileExistsError:

        return False, (
            "A file or folder with this name already exists."
        )

    except (ValueError, OSError):

        return False, "Unable to create folder."


# ==========================================================
# DELETE FILE
# ==========================================================

def delete_file(relative_path):
    """Delete an existing NAS file."""

    try:

        file_path, _ = _safe_path(relative_path)

        if not os.path.isfile(file_path):
            return False

        os.remove(file_path)

        return True

    except (ValueError, OSError):

        return False


# ==========================================================
# GET FILE PATH
# ==========================================================

def get_file_path(relative_path):
    """Return a validated path to an existing file."""

    try:

        file_path, _ = _safe_path(relative_path)

        if not os.path.isfile(file_path):
            return None

        return file_path

    except (ValueError, OSError):

        return None


# ==========================================================
# RENAME FILE OR FOLDER
# ==========================================================

def rename_item(relative_path, new_name):
    """Safely rename a file or folder."""

    new_name = new_name.strip()

    if (
        not new_name
        or new_name in (".", "..")
        or "/" in new_name
        or "\\" in new_name
        or "\x00" in new_name
        or len(new_name) > 255
    ):
        return False, "Invalid new name."

    safe_name = secure_filename(new_name)

    if not safe_name:
        return False, "Invalid new name."

    try:

        source, normalized_path = _safe_path(relative_path)

        if not normalized_path:
            return False, "Cannot rename main storage."

        if not os.path.lexists(source):
            return False, "File or folder not found."

        parent = os.path.dirname(source)

        destination = os.path.join(parent, safe_name)

        if os.path.lexists(destination):
            return False, (
                "A file or folder with this name already exists."
            )

        os.rename(source, destination)

        return True, (
            f"Renamed successfully to '{safe_name}'."
        )

    except (ValueError, OSError):

        return False, "Unable to rename file or folder."


# ==========================================================
# DELETE EMPTY FOLDER
# ==========================================================

def delete_folder(relative_path):
    """Delete an empty folder safely inside NAS storage."""

    try:

        folder_path, normalized_path = _safe_path(relative_path)

        if not normalized_path:
            return False, (
                "Cannot delete the main storage folder."
            )

        if not os.path.isdir(folder_path):
            return False, "Folder not found."

        os.rmdir(folder_path)

        return True, "Folder deleted successfully."

    except ValueError:

        return False, "Invalid folder path."

    except OSError:

        return False, (
            "Folder is not empty or cannot be deleted."
        )

