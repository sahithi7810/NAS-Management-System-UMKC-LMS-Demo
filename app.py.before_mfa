import logging
import re
from pathlib import Path
from collections import deque
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
load_dotenv()
from modules.backup_manager import (
    BACKUP_DIR,
    create_backup,
    list_backups,
    delete_backup,
    restore_backup
)
from modules.file_sharing import (
    can_access_file,
    share_file,
    get_file_shares,
    revoke_file_access,
    filter_accessible_items,
    get_user,
    get_file_record
)
from modules.recycle_bin import (
    move_to_recycle_bin,
    get_recycle_bin_items,
    restore_from_recycle_bin,
    permanently_delete_item,
    cleanup_expired_items
)
from werkzeug.utils import secure_filename

from modules.storage_audit import (
    can_user_upload,
    record_upload,
    record_download,
    record_delete,
    record_rename,
    get_admin_storage_data,
    get_student_storage_data,
    set_user_quota
)

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
from modules.file_manager import upload_file, get_all_files, delete_file, create_folder, get_file_path, rename_item, delete_folder, STORAGE_FOLDER
from config import Config

from modules.password_reset import (
    init_password_reset_table,
    create_reset_token,
    invalidate_reset_token,
    is_reset_token_valid,
    perform_password_reset,
    send_password_reset_email,
    get_reset_csrf_token,
    verify_reset_csrf_token
)

from modules.auth import register_user, verify_user, change_password
from modules.mfa import (
    is_mfa_enabled,
    begin_mfa_enrollment,
    confirm_mfa_enrollment,
    verify_mfa_code
)
from modules.monitor import get_system_info
from modules.user_manager import get_all_users, update_user_role, toggle_user_status, delete_user, update_user_details

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY
LOG_FILE = Path(__file__).resolve().parent / "server.log"

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=1000000,
    backupCount=3,
    encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
werkzeug_logger = logging.getLogger("werkzeug")
werkzeug_logger.setLevel(logging.INFO)
werkzeug_logger.addHandler(file_handler)
app.logger.info("NAS application logging initialized")
   

@app.route("/")
def home():

    if session.get("username"):
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not username or not email or len(password) < 8:
            flash("Enter a username, email and password pf at least 8 characters.")
            return redirect(url_for("register"))
        try:
             register_user(username, email, password)
             flash("Registration successful. Please log in.")
             return redirect(url_for("home"))
        except Exception:
            flash("Registration failed. Username or email may alredy exist.")
            return redirect(url_for("register"))

    return render_template("register.html")


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = verify_user(username, password)

    if user:
        session.clear()

        username = user["username"]
        role = user.get("role") or "user"

        if is_mfa_enabled(username):
            session["mfa_pending_user"] = username
            session["mfa_pending_role"] = role
            return redirect(url_for("mfa_verify"))

        if role == "admin":
            session["mfa_pending_user"] = username
            session["mfa_pending_role"] = role
            return redirect(url_for("mfa_setup"))

        # Student accounts can enable MFA voluntarily.
        session["username"] = username
        session["role"] = role

        return redirect(url_for("dashboard"))

    flash("Invalid username or password.")
    return redirect(url_for("home"))


@app.route("/mfa/setup", methods=["GET", "POST"])
def mfa_setup():
    username = (
        session.get("mfa_pending_user")
        or session.get("username")
    )

    if not username:
        return redirect(url_for("home"))

    if request.method == "POST":
        success, codes, message = confirm_mfa_enrollment(
            username,
            request.form.get("code", "")
        )

        if not success:
            flash(message)
            return redirect(url_for("mfa_setup"))

        # Complete the administrator's pending login.
        if session.get("mfa_pending_user"):
            role = session.get("mfa_pending_role", "user")

            session.clear()
            session["username"] = username
            session["role"] = role

        return render_template(
            "mfa_recovery_codes.html",
            recovery_codes=codes
        )

    try:
        secret, qr_data_uri = begin_mfa_enrollment(username)

    except ValueError as error:
        flash(str(error))
        return redirect(url_for("dashboard"))

    return render_template(
        "mfa_setup.html",
        qr_data_uri=qr_data_uri,
        manual_secret=secret
    )


@app.route("/mfa/verify", methods=["GET", "POST"])
def mfa_verify():
    username = session.get("mfa_pending_user")
    role = session.get("mfa_pending_role", "user")

    if not username:
        return redirect(url_for("home"))

    if request.method == "POST":
        code = request.form.get("code", "")

        if verify_mfa_code(username, code):
            session.clear()
            session["username"] = username
            session["role"] = role

            flash("MFA verification successful.")
            return redirect(url_for("dashboard"))

        flash("Incorrect or already-used verification code.")

    return render_template("mfa_verify.html")
@app.route("/dashboard")
def dashboard():
    if not session.get("username"):
        return redirect(url_for("home"))

    return render_template("dashboard.html")

@app.route("/api/system-info")
def system_info():
    if not session.get("username"):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        return jsonify(get_system_info())
    except Exception:
        app.logger.exception("System information API failed")
        return jsonify({"error": "Unable to load system information"}), 500
@app.route("/monitor")
def monitor():
    if not session.get("username"):
        return redirect(url_for("home"))
    return render_template("monitor.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))



@app.route("/files", methods=["GET", "POST"])
def files():
    if not session.get("username"):
        return redirect(url_for("home"))

    current_path = (
        request.form.get("current_path", "")
        if request.method == "POST"
        else request.args.get("path", "")
    )

    if request.method == "POST":

        uploaded_file = request.files.get("file")

        if not uploaded_file or not uploaded_file.filename:
            flash("Please select a file.")
            return redirect(url_for("files", path=current_path))

        safe_filename = secure_filename(uploaded_file.filename)

        if not safe_filename:
            flash("Invalid filename.")
            return redirect(url_for("files", path=current_path))

        # Determine the uploaded file size before saving.
        try:
            stream = uploaded_file.stream
            original_position = stream.tell()
            stream.seek(0, 2)
            incoming_size = stream.tell()
            stream.seek(original_position)
        except (OSError, AttributeError):
            flash("Unable to determine file size.")
            return redirect(url_for("files", path=current_path))

        # Check the student's storage quota.
        allowed, message = can_user_upload(
            session["username"],
            incoming_size
        )

        if not allowed:
            flash(message, "danger")
            return redirect(url_for("files", path=current_path))

        # Save the file using the existing File Manager.
        if not upload_file(uploaded_file, current_path):
            flash("Upload failed. Check the file and folder.", "danger")
            return redirect(url_for("files", path=current_path))

        relative_path = "/".join(
            part
            for part in (current_path.strip("/"), safe_filename)
            if part
        )

        saved_path = get_file_path(relative_path)

        try:
            if not saved_path:
                raise RuntimeError("Uploaded file could not be located.")

            actual_size = Path(saved_path).stat().st_size

            # Store ownership and upload activity in MySQL.
            record_upload(
                session["username"],
                relative_path,
                actual_size
            )

            app.logger.info(
                "File uploaded by %s: %s (%s bytes)",
                session["username"],
                relative_path,
                actual_size
            )

            flash("File uploaded successfully!", "success")

        except Exception:
            # Avoid leaving a file without an ownership record.
            delete_file(relative_path)

            app.logger.exception(
                "Upload tracking failed for %s",
                relative_path
            )

            flash(
                "Upload could not be recorded. Please try again.",
                "danger"
            )

        return redirect(url_for("files", path=current_path))

    try:
        files_list = get_all_files(current_path)
        files_list = filter_accessible_items(
            session["username"],
            files_list,
            current_path
        )
    except (ValueError, OSError):
        flash("Invalid or unavailable folder.", "danger")
        return redirect(url_for("files"))

    parent_path = current_path.rpartition("/")[0]

    return render_template(
        "files.html",
        files=files_list,
        current_path=current_path,
        parent_path=parent_path
    )

@app.route("/folder/create", methods=["POST"])
def create_folder_route():
    if not session.get("username"):
        return redirect(url_for("home"))
    if session.get("role") != "admin":
        flash("Administrator access required.")
        return redirect(url_for("files"))
    folder_name = request.form.get("folder_name", "")
    current_path = request.form.get("current_path", "")
    success, message = create_folder(folder_name, current_path)
    flash(message)
    return redirect(url_for("files", path=current_path))


@app.route("/folder/delete", methods=["POST"])
def delete_folder_route():

    if not session.get("username"):
        return redirect(url_for("home"))

    if session.get("role") != "admin":
        flash("Professor/Admin access required.", "danger")
        return redirect(url_for("files"))

    folder_path = request.form.get("folder_path", "").strip()
    current_path = request.form.get("current_path", "")

    if not folder_path:
        flash("Folder path is missing.", "danger")
        return redirect(url_for("files", path=current_path))

    if (
        folder_path == ".recycle_bin"
        or folder_path.startswith(".recycle_bin/")
    ):
        flash("Cannot delete the internal Recycle Bin folder.", "danger")
        return redirect(url_for("files", path=current_path))

    try:
        success, message = move_to_recycle_bin(
            session["username"],
            folder_path
        )

        flash(
            message,
            "success" if success else "danger"
        )

        if success:
            app.logger.info(
                "Folder moved to Recycle Bin by %s: %s",
                session["username"],
                folder_path
            )

    except Exception:
        app.logger.exception("Recycle Bin folder operation failed")
        flash("Unable to move folder to Recycle Bin.", "danger")

    return redirect(url_for("files", path=current_path))


@app.route("/rename", methods=["POST"])
def rename_item_route():

    if not session.get("username"):
        return redirect(url_for("home"))

    old_path = request.form.get("old_path", "")
    new_name = request.form.get("new_name", "").strip()
    current_path = request.form.get("current_path", "")

    try:
        # Individual file sharing currently supports file renaming.
        file_path = get_file_path(old_path)

        if file_path:
            if not can_access_file(
                session["username"],
                old_path,
                "edit"
            ):
                flash("You do not have permission to rename this file.", "danger")
                return redirect(url_for("files", path=current_path))

        elif session.get("role") != "admin":
            flash("Only the Professor can rename folders.", "danger")
            return redirect(url_for("files", path=current_path))

        success, message = rename_item(old_path, new_name)

        if success and file_path:
            new_path = "/".join(
                part
                for part in (
                    old_path.rpartition("/")[0],
                    secure_filename(new_name)
                )
                if part
            )

            record_rename(
                session["username"],
                old_path,
                new_path
            )

        flash(message, "success" if success else "danger")

    except Exception:
        app.logger.exception("Rename operation failed")
        flash("Unable to rename file or folder.", "danger")

    return redirect(url_for("files", path=current_path))


@app.route("/download/<path:filename>")
def download(filename):

    if not session.get("username"):
        return redirect(url_for("home"))

    if not can_access_file(
        session["username"],
        filename,
        "read"
    ):
        flash("You do not have permission to access this file.", "danger")
        return redirect(url_for("files"))

    file_path = get_file_path(filename)

    if not file_path:
        flash("File not found.", "danger")
        return redirect(url_for("files"))

    file_size = Path(file_path).stat().st_size

    try:
        record_download(

            session["username"],
            filename,
            file_size
        )

        app.logger.info(
            "File downloaded by %s: %s",
            session["username"],
            filename
        )

    except Exception:
        app.logger.exception("Download activity logging failed")
        flash("Unable to record download activity.", "danger")
        return redirect(url_for("files"))

    return send_from_directory(
        STORAGE_FOLDER,
        filename,
        as_attachment=True
    )

    



@app.route("/delete/<path:filename>", methods=["POST"])
def delete(filename):

    if not session.get("username"):
        return redirect(url_for("home"))

    parent_path = filename.rpartition("/")[0]

    # Keep the recycle-bin storage private.
    if filename == ".recycle_bin" or filename.startswith(".recycle_bin/"):
        flash("Direct access to Recycle Bin storage is not allowed.", "danger")
        return redirect(url_for("files"))

    # Require Edit permission.
    if not can_access_file(
        session["username"],
        filename,
        "edit"
    ):
        flash("You do not have permission to delete this file.", "danger")
        return redirect(url_for("files", path=parent_path))

    try:
        success, message = move_to_recycle_bin(
            session["username"],
            filename
        )

        flash(
            message,
            "success" if success else "danger"
        )

        app.logger.info(
            "Recycle Bin operation by %s: %s - %s",
            session["username"],
            filename,
            message
        )

    except Exception:
        app.logger.exception("Recycle Bin file deletion failed")
        flash("Unable to move file to Recycle Bin.", "danger")

    return redirect(url_for("files", path=parent_path))

    
@app.route("/users")
def manage_users():

    if not session.get("username"):
        return redirect(url_for("home"))

    if session.get("role") != "admin":
        flash("Administrator access required.")
        return redirect(url_for("dashboard"))

    users = get_all_users()

    return render_template(
        "users.html",
        users=users
    )
@app.route("/users/add", methods=["POST"])
def add_user():

    if not session.get("username"):
        return redirect(url_for("home"))

    if session.get("role") != "admin":
        flash("Administrator access required.")
        return redirect(url_for("dashboard"))

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not username or not email or len(password) < 8:
        flash("Enter all details. Password must have at least 8 characters.")
        return redirect(url_for("manage_users"))
    try:
        register_user(username, email, password)
        flash("New user created successfully.")
    except Exception:
        app.logger.exception("User creation failed")
        flash("Could not create user. Usesrname or email may already exist.")
    return redirect(url_for("manage_users"))

@app.route("/users/<int:user_id>/role", methods=["POST"])
def change_user_role(user_id):
    if not session.get("username"):
        return redirect(url_for("home"))

    if session.get("role") != "admin":
        flash("Administrator access required.")
        return redirect(url_for("dashboard"))
    new_role = request.form.get("role", "")
    try:
        success, message = update_user_role(
            user_id,
            new_role,
            session.get("username")
        )
        flash(message)

    except Exception:
        app.logger.exception("User role update failed")
        flash("Unable to update role.")
    return redirect(url_for("manage_users"))

@app.route("/users/<int:user_id>/status", methods=["POST"])
def change_user_status(user_id):
    if not session.get("username"):
        return redirect(url_for("home"))
    if session.get("role") != "admin":
        flash("Administrator access required.")
        return redirect(url_for("dashboard"))

    try:
        desired_status = 1 if request.form.get("action") == "activate" else 0
        success, message = toggle_user_status(
            user_id,
            desired_status,
            session.get("username")
        )
        flash(message)
    except Exception:
        app.logger.exception("User status update failed")
        flash("Unable to update user status.")
    return redirect(url_for("manage_users"))

@app.route("/users/<int:user_id>/delete", methods=["POST"])
def remove_user(user_id):
    if not session.get("username"):
        return redirect(url_for("home"))
    if session.get("role") != "admin":
        flash("Administrator access required.")
        return redirect(url_for("dashboard"))
    try:
        success, message = delete_user(
            user_id,
            session.get("username")
        )
        flash(message)
    except Exception:
        app.logger.exception("User deletion failed")
        flash("Unable to delete user.")
    return redirect(url_for("manage_users"))

@app.route("/users/<int:user_id>/edit", methods=["POST"])
def edit_user(user_id):
    if not session.get("username"):
        return redirect(url_for("home"))
    if session.get("role") != "admin":
        flash("Administrator access required.")
        return redirect(url_for("dashboard"))
    new_username = request.form.get("username", "").strip()
    new_email = request.form.get("email", "").strip()
    if not new_username or not new_email:
        flash("Username and email are required.")
        return redirect(url_for("manage_users"))

    if len(new_username) > 100 or len(new_email) > 150:
        flash("username or email is too long.")
        return redirect(url_for("manage_users"))

    try:
        success, message = update_user_details(
            user_id,
            new_username,
            new_email,
            session.get("username")
        )
        flash(message)
    except Exception:
        app.logger.exception("User details update failed")
        flash("Unable to update user details.")
    return redirect(url_for("manage_users"))

@app.route("/change_password", methods=["GET", "POST"])
def change_password_page():
    if not session.get("username"):
        return redirect(url_for("home"))
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if len(new_password) < 8:
            flash("New password must have at least 8 characters.")
            return redirect(url_for("change_password_page"))
        if new_password != confirm_password:
            flash("New password do not match.")
            return redirect(url_for("change_password_page"))
        try:
            success, message = change_password(
                session.get("username"),
                current_password,
                new_password
            )
            flash(message)
            if success:
                return redirect(url_for("dashboard"))
        except Exception:
            app.logger.exception("Password change failed")
            flash("unable to change password. Please try again.")
        return redirect(url_for("change_password_page"))
    return render_template("change_password.html")

@app.route("/system-logs")
def system_logs():
    if not session.get("username"):
        return redirect(url_for("home"))
    if session.get("role") != "admin":
        flash("Administrator access required.")
        return redirect(url_for("dashboard"))
    log_entries = []
    try: 
        if LOG_FILE.exists():
            with LOG_FILE.open(
                "r", encoding="utf-8", errors="replace"
            ) as log_file:
                recent_lines = deque(log_file, maxlen=200)
                ansi_escape = re.compile(r"\x1B\[[0-?]*[-/]*[@-~]")
                log_entries = [
                    ansi_escape.sub("", line).strip()
                    for line in recent_lines
                    if line.strip()
                ][-200:]
    except OSError:
        app.logger.exception("Unable to read server log")
        flash("Unable to read server log.")
    return render_template(
        "system_logs.html",
        log_entries=log_entries
    )

def backup_admin_access():
    """Allow only logged-in administrators to manage backups."""
    if not session.get("username"):
        return redirect(url_for("home"))
    if session.get("role") != "admin":
        flash("Administartor access required.", "danger")
        return redirect(url_for("dashboard"))
    return None
@app.route("/backups", methods=["GET"])
def backup_management():
    access = backup_admin_access()
    if access is not None:
        return access
    backups = list_backups()
    return render_template("backups.html", backups=backups)
@app.route("/backups/create", methods=["POST"])
def backup_create():
    access = backup_admin_access()
    if access is not None:
        return access
    success, message = create_backup()
    if success:
        flash("Backup created successfully: " + message, "success")
    else: 
        flash("Backup creation failed: " + message, "danger")
    return redirect(url_for("backup_management"))

@app.route("/backups/restore/<filename>", methods=["POST"])
def backup_restore(filename):
    access = backup_admin_access()
    if access is not None:
        return access
    success, message = restore_backup(filename)
    flash(
        message,
        "success" if success else "danger"
    )
    return redirect(url_for("backup_management"))
@app.route("/backups/delete/<filename>", methods=["POST"])
def backup_delete(filename):
    access = backup_admin_access()
    if access is not None:
        return access
    success, message = delete_backup(filename)
    flash(
        message,
        "success" if success else "danger"
    )
    return redirect(url_for("backup_management"))
@app.route("/backups/download/<filename>")
def backup_download(filename):
    access = backup_admin_access()
    if access is not None:
        return access
    available_name = {
        backup["name"] for backup in list_backups()
    }
    if filename not in available_name:
        flash("backup file not found.", "danger")
        return redirect(url_for("backup_management"))
    return send_from_directory(
        BACKUP_DIR,
        filename,
        as_attachment=True
    )


# ==========================================================
# PROFESSOR / ADMIN STORAGE DASHBOARD
# ==========================================================

@app.route("/admin/storage")
def admin_storage():

    if not session.get("username"):
        return redirect(url_for("home"))

    if session.get("role") != "admin":
        flash("Professor access required.", "danger")
        return redirect(url_for("dashboard"))

    try:
        storage_data = get_admin_storage_data()

        return render_template(
            "admin_storage.html",
            students=storage_data["students"],
            activities=storage_data["activities"],
            disk_total_bytes=storage_data["disk_total_bytes"],
            disk_used_bytes=storage_data["disk_used_bytes"],
            disk_free_bytes=storage_data["disk_free_bytes"]
        )

    except Exception:
        app.logger.exception("Admin storage dashboard failed")
        flash("Unable to load storage information.", "danger")
        return redirect(url_for("dashboard"))


# ==========================================================
# PROFESSOR SETS INDIVIDUAL STUDENT STORAGE QUOTA
# ==========================================================

@app.route("/admin/storage/<int:user_id>/quota", methods=["POST"])
def admin_set_storage_quota(user_id):

    if not session.get("username"):
        return redirect(url_for("home"))

    if session.get("role") != "admin":
        flash("Professor access required.", "danger")
        return redirect(url_for("dashboard"))

    quota_gb = request.form.get("quota_gb", "")

    try:
        success, message = set_user_quota(user_id, quota_gb)

        flash(
            message,
            "success" if success else "danger"
        )

    except Exception:
        app.logger.exception("Student storage quota update failed")
        flash("Unable to update student storage quota.", "danger")

    return redirect(url_for("admin_storage"))


# ==========================================================
# STUDENT PERSONAL STORAGE DASHBOARD
# ==========================================================

@app.route("/my-storage")
def my_storage():

    if not session.get("username"):
        return redirect(url_for("home"))

    if session.get("role") == "admin":
        return redirect(url_for("admin_storage"))

    try:
        storage_data = get_student_storage_data(
            session["username"]
        )

        if not storage_data:
            flash("Unable to find your storage information.", "danger")
            return redirect(url_for("dashboard"))

        return render_template(
            "student_storage.html",
            summary=storage_data["summary"],
            files=storage_data["files"],
            activities=storage_data["activities"]
        )

    except Exception:
        app.logger.exception("Student storage dashboard failed")
        flash("Unable to load your storage information.", "danger")
        return redirect(url_for("dashboard"))

# ==========================================================
# SHARE FILE WITH ANOTHER STUDENT
# ==========================================================

@app.route("/share/<path:filename>", methods=["GET", "POST"])
def manage_file_shares(filename):

    if not session.get("username"):
        return redirect(url_for("home"))

    file_path = get_file_path(filename)
    file_record = get_file_record(filename)
    current_user = get_user(session["username"])

    if not file_path or not file_record or not current_user:
        flash("File or ownership record not found.", "danger")
        return redirect(url_for("files"))

    # Only the file owner or Professor can manage sharing.
    if (
        current_user["role"] != "admin"
        and file_record["owner_user_id"] != current_user["id"]
    ):
        flash("Only the file owner or Professor can share this file.", "danger")
        return redirect(url_for("files"))

    if request.method == "POST":

        recipient = request.form.get(
            "recipient_username", ""
        ).strip()

        permission = request.form.get(
            "permission", ""
        ).strip()

        try:
            success, message = share_file(
                session["username"],
                filename,
                recipient,
                permission
            )

            flash(
                message,
                "success" if success else "danger"
            )

        except Exception:
            app.logger.exception("File sharing failed")
            flash("Unable to share this file.", "danger")

        return redirect(
            url_for("manage_file_shares", filename=filename)
        )

    students = [
        user for user in get_all_users()
        if user["role"] == "user" and user["is_active"]
    ]

    shares = get_file_shares(
        session["username"],
        filename
    )

    return render_template(
        "share_file.html",
        filename=filename,
        shares=shares,
        students=students
    )


# ==========================================================
# REVOKE FILE SHARING ACCESS
# ==========================================================

@app.route("/share/revoke/<int:share_id>", methods=["POST"])
def revoke_shared_file(share_id):

    if not session.get("username"):
        return redirect(url_for("home"))

    filename = request.form.get("filename", "")

    try:
        success, message = revoke_file_access(
            session["username"],
            share_id
        )

        flash(
            message,
            "success" if success else "danger"
        )

    except Exception:
        app.logger.exception("File sharing revocation failed")
        flash("Unable to revoke file access.", "danger")

    if filename:
        return redirect(
            url_for("manage_file_shares", filename=filename)
        )

    return redirect(url_for("files"))

# ==========================================================
# RECYCLE BIN - VIEW DELETED ITEMS
# ==========================================================

@app.route("/recycle-bin")
def recycle_bin_page():

    if not session.get("username"):
        return redirect(url_for("home"))

    try:
        items = get_recycle_bin_items(
            session["username"]
        )

        return render_template(
            "recycle_bin.html",
            items=items
        )

    except Exception:
        app.logger.exception("Unable to load Recycle Bin")
        flash("Unable to load Recycle Bin.", "danger")
        return redirect(url_for("files"))


# ==========================================================
# RESTORE ONE ITEM
# ==========================================================

@app.route("/recycle-bin/restore/<int:item_id>", methods=["POST"])
def recycle_bin_restore(item_id):

    if not session.get("username"):
        return redirect(url_for("home"))

    try:
        success, message = restore_from_recycle_bin(
            session["username"],
            item_id
        )

        flash(
            message,
            "success" if success else "danger"
        )

    except Exception:
        app.logger.exception("Recycle Bin restore route failed")
        flash("Unable to restore this item.", "danger")

    return redirect(url_for("recycle_bin_page"))


# ==========================================================
# PERMANENTLY DELETE ONE ITEM
# ==========================================================

@app.route("/recycle-bin/permanent-delete/<int:item_id>", methods=["POST"])
def recycle_bin_permanent_delete(item_id):

    if not session.get("username"):
        return redirect(url_for("home"))

    try:
        success, message = permanently_delete_item(
            session["username"],
            item_id
        )

        flash(
            message,
            "success" if success else "danger"
        )

    except Exception:
        app.logger.exception("Permanent deletion route failed")
        flash("Unable to permanently delete item.", "danger")

    return redirect(url_for("recycle_bin_page"))


# ==========================================================
# PERMANENTLY DELETE SELECTED ITEMS
# ==========================================================

@app.route("/recycle-bin/delete-selected", methods=["POST"])
def recycle_bin_delete_selected():

    if not session.get("username"):
        return redirect(url_for("home"))

    selected_ids = request.form.getlist("item_ids")

    if not selected_ids:
        flash("Please select at least one item.", "warning")
        return redirect(url_for("recycle_bin_page"))

    deleted_count = 0
    failed_count = 0

    for item_id in selected_ids:

        try:
            item_id = int(item_id)

            success, message = permanently_delete_item(
                session["username"],
                item_id
            )

            if success:
                deleted_count += 1
            else:
                failed_count += 1

        except (ValueError, TypeError):
            failed_count += 1

        except Exception:
            app.logger.exception(
                "Unable to permanently delete Recycle Bin item"
            )
            failed_count += 1

    if deleted_count:
        flash(
            f"{deleted_count} item(s) permanently deleted.",
            "success"
        )

    if failed_count:
        flash(
            f"{failed_count} item(s) could not be deleted.",
            "danger"
        )

    return redirect(url_for("recycle_bin_page"))
@app.route("/recycle-bin")
def view_recycle_bin():
    if not session.get("username"):
        return redirect(url_for("login"))

    items = get_recycle_bin_items(session["username"])

    return render_template(
        "recycle_bin.html",
        items=items
    )


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    csrf_token = get_reset_csrf_token(session)

    if request.method == "POST":
        if not verify_reset_csrf_token(
            session,
            request.form.get("csrf_token", "")
        ):
            return "Invalid form request. Please reload the page.", 400

        email = request.form.get("email", "").strip()

        try:
            reset_data = create_reset_token(email)

            if reset_data:
                token, recipient = reset_data

                try:
                    import os

                    public_base = os.getenv(
                        "PUBLIC_BASE_URL", ""
                    ).strip().rstrip("/")

                    reset_path = url_for(
                        "reset_password_page",
                        token=token
                    )

                    if public_base:
                        reset_link = public_base + reset_path
                    else:
                        reset_link = (
                            request.url_root.rstrip("/") + reset_path
                        )

                    send_password_reset_email(
                        recipient,
                        reset_link
                    )

                except Exception:
                    invalidate_reset_token(token)
                    app.logger.exception(
                        "Password reset email delivery failed"
                    )

        except Exception:
            app.logger.exception(
                "Password reset request could not be processed"
            )

        # This message is the same whether or not the account exists.
        flash(
            "If an active account uses that email address, "
            "a password reset link will be sent shortly."
        )
        return redirect(url_for("forgot_password"))

    return render_template(
        "forgot_password.html",
        csrf_token=csrf_token
    )


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password_page(token):
    csrf_token = get_reset_csrf_token(session)

    if not is_reset_token_valid(token):
        flash("This password reset link is invalid or expired.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        if not verify_reset_csrf_token(
            session,
            request.form.get("csrf_token", "")
        ):
            return "Invalid form request. Please reload the page.", 400

        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(password) < 8:
            flash("Your password must contain at least 8 characters.")

        elif password != confirm_password:
            flash("The passwords do not match.")

        else:
            try:
                success = perform_password_reset(token, password)

                if success:
                    session.clear()
                    flash(
                        "Your password has been reset successfully. "
                        "Please log in with your new password."
                    )
                    return redirect(url_for("home"))

                flash(
                    "The reset link is invalid, expired or already used."
                )
                return redirect(url_for("forgot_password"))

            except Exception:
                app.logger.exception("Password reset failed")
                flash("Unable to reset the password. Please try again.")

    return render_template(
        "reset_password.html",
        token=token,
        csrf_token=csrf_token
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)


