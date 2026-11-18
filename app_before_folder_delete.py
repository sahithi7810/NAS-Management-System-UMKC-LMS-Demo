


from dotenv import load_dotenv
load_dotenv()


from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
from modules.file_manager import upload_file, get_all_files, delete_file, create_folder, get_file_path, rename_item, STORAGE_FOLDER
from config import Config
from modules.auth import register_user, verify_user, change_password
from modules.monitor import get_system_info
from modules.user_manager import get_all_users, update_user_role, toggle_user_status, delete_user, update_user_details

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY


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
        session["username"] = user["username"]
        session["role"] = user["role"]
        return redirect(url_for("dashboard"))
    flash ("Invalid username or password.")
    return redirect(url_for("home"))


@app.route("/dashboard")
def dashboard():
    if not session.get("username"):
        return redirect(url_for("home"))

    return render_template("dashboard.html")

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

        if upload_file(uploaded_file, current_path):
            flash("File uploaded successfully!")
        else:
            flash("Upload failed. Check the file and folder.")
        return redirect(url_for("files", path=current_path))
    try:
        files_list = get_all_files(current_path)
        
    except (ValueError, OSError):
        flash("Invalid or unavailable folder.")
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
@app.route("/rename", methods=["POST"])
def rename_item_route():
    if not session.get("username"):
        return redirect(url_for("home"))
    if session.get("role") != "admin":
        flash("Administrator access required.")
        return redirect(url_for("files"))
    old_path = request.form.get("old_path", "")
    new_name = request.form.get("new_name", "")
    current_path = request.form.get("current_path", "")
    try:
        success, message = rename_item(old_path, new_name)
        flash(message)
    except Exception:
        app.logger.exception("Rename operation failed")
        flash("unable to rename file or folder.")
    return redirect(url_for("files", path=current_path))


@app.route("/download/<path:filename>")
def download(filename):
    if not session.get("username"):
        return redirect(url_for("home"))
    file_path = get_file_path(filename)
    if not file_path:
        flash("File not found.")
        return redirect(url_for("files"))

    return send_from_directory(STORAGE_FOLDER, filename, as_attachment=True)

@app.route("/delete/<path:filename>", methods=["POST"])
def delete(filename):
    if not session.get("username"):
        return redirect(url_for("home"))
    parent_path = filename.rpartition("/")[0]

    if delete_file(filename):
        flash("File deleted successfully!")
    else:
        flash("File not found or could not be deleted.")
    return redirect(url_for("files", path=parent_path))

@app.route("/api/system-info")
def system_info():
    if not session.get("username"):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(get_system_info())

@app.route("/users")
def manage_users():
    if not session.get("username"):
        return redirect(url_for("home"))
    if session.get("role") != "admin":
        flash("Administrator access required.")
        return redirect(url_for("dashboard"))
    users = get_all_users()
    return render_template("users.html", users=users)


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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)


