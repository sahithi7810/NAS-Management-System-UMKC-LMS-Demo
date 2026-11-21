
UMKC LMS Demo

A Web-Based Learning and Network Attached Storage (NAS) Management System Learn • Collaborate • Lead

Unofficial student project. This is not an official UMKC product. It is an LMS/NAS demonstration platform and is not hardened for production use or real student data.

Table of Contents
Overview
Features
Tech Stack
Architecture
User Roles
Project Structure
Database
Routes
Installation & Setup
Backups
Security
Project Status
Known Issues
Future Enhancements
Overview

UMKC LMS Demo is a secure, web-based platform where an administrator (professor) can manage student accounts, storage quotas, files, system resources and backups, while students can upload, download, organize and share their files.

It combines LMS-style user access with NAS capabilities: centralized file management, per-student storage management, file access control, activity tracking, and backup/recovery.

Scope note: The project does not currently include assignment posting, assignment submission, or assignment-related email notifications.

Features
Module	Description
Authentication & User Management	Registration, login, password hashing (Werkzeug), role-based access, enable/disable accounts, password change
Multi-Factor Authentication (MFA)	TOTP via Google/Microsoft Authenticator, QR enrollment, 10 one-time recovery codes (hashed), Fernet-encrypted secrets
File Management	Upload, download, list, create folders, rename, navigate, delete via Recycle Bin, safe path validation
File Sharing	Private by default; share with Read or Edit permission; revoke access; ownership checks
Storage & Quotas	Default 5 GB quota per student, admin-adjustable, usage tracking, 90% alert logic, activity logs
Recycle Bin	Restore or permanently delete files/folders; 30-day auto-expiry via cleanup script
Backup & Restore	Manual and automatic backups of NAS storage + MySQL dump, compressed archives, SHA-256 checksums, Dropbox off-site copy, 30-day retention
System Monitoring	CPU, RAM and disk usage with progress bars via /api/system-info
Logging	Flask/server logs plus MySQL activity records (logins, uploads, downloads, deletes, sharing, backups, errors)
Password Reset	Single-use, hashed, 15-minute expiring reset tokens (email delivery via Gmail SMTP)
UI / Theme	UMKC navy and gold, campus background, responsive Bootstrap 5 layout, shared CSS
Tech Stack
Technology	Purpose
Python	Backend language
Flask	Web framework
HTML5 / CSS3 / Bootstrap 5 / JavaScript	Frontend
MySQL 8.4	Database
Ubuntu Server (in VirtualBox)	Hosting environment
Dropbox	Off-site backup storage
Gmail SMTP	Password-reset / alert emails (testing in progress)
Google / Microsoft Authenticator	TOTP MFA
Python system libraries	CPU, memory, disk monitoring
Gunicorn / WSGI	Potential production layer (not yet confirmed configured)
ngrok	Public HTTPS tunnel for demos only
Architecture

A three-layer architecture:

Presentation Layer — Browser, login, dashboard, file/admin/student pages (HTML, CSS, Bootstrap, JS)
Application Layer — Flask routes, authentication, sharing, quotas, backups, recycle bin, monitoring (Python, Flask)
Data & Storage Layer — MySQL, NAS storage folder, recycle bin, local backups, Dropbox

Request flow: Browser → Flask checks login and permissions → Python modules process the request → MySQL stores metadata, permissions and activity → filesystem stores the actual files → response returns to the browser.

Uploaded file contents live in the NAS storage/ directory. The database stores only metadata about them.

User Roles
Capability	Admin / Professor	Student
Login	Yes	Yes
MFA	Mandatory for initial admin setup	Optional
Manage accounts	Yes	No
Upload / download files	Yes	Yes (per permission)
Share files	Administrative access	Share owned files
Set storage quota	Yes	No
View storage	All students	Own storage
View system logs	Yes	No
System monitoring	Yes	No
Manage backups	Yes	No
Recycle Bin	Manage all records	Manage own deleted items
Project Structure

Logical overview, not a verified live directory listing.

NAS-Management-System/
├── app.py
├── config.py
├── database.py
├── .env
│
├── modules/
│   ├── auth.py
│   ├── user_manager.py
│   ├── file_manager.py
│   ├── file_sharing.py
│   ├── storage_audit.py
│   ├── recycle_bin.py
│   ├── backup_manager.py
│   ├── monitor.py
│   ├── mfa.py
│   └── password_reset.py
│
├── templates/
│   ├── login.html, register.html, dashboard.html
│   ├── files.html, users.html, monitor.html
│   ├── system_logs.html, backups.html, recycle_bin.html
│   ├── admin_storage.html, student_storage.html, share_file.html
│   ├── mfa_setup.html, mfa_verify.html, mfa_recovery_codes.html
│   └── forgot_password.html, reset_password.html
│
├── static/
│   ├── css/umkc-theme.css
│   └── lms/umkc-campus-bg.png
│
├── storage/              # uploaded student and admin files
├── backups/automatic/
├── scripts/
│   ├── automatic_backup.py
│   └── cleanup_recycle_bin.py
├── logs/automatic_backup.log
└── venv/
Database

Database name: nas_management (connection via config.py, database.py, .env).

Table	Purpose
users	Accounts, credentials, roles, status (+ mfa_enabled, mfa_secret, mfa_pending_secret, mfa_enrolled_at)
file_shares	File owners, recipients, permission levels
storage_file_records	File ownership, names, paths, sizes
storage_activity_logs	Student file activity history
storage_user_quotas	Per-user storage allowance
storage_alert_states	Tracks 90% notification state
recycle_bin_items	Deleted items, owners, expiry, restore status
mfa_recovery_codes	Hashed MFA recovery codes
password_reset_tokens	Hashed reset tokens and expiry
Routes
Route	Purpose
/	Login page
/register	Registration
/login	Login authentication
/dashboard	Main dashboard
/logout	Logout
/files	File manager
/download/...	Download files
/delete/...	Move to Recycle Bin
/rename	Rename files
/users	Manage accounts
/monitor	System monitoring
/api/system-info	System information API (JSON)
/system-logs	System logs
/backups	Backup management
/admin/storage	Admin storage dashboard
/my-storage	Student storage dashboard
/share/...	Share files
/recycle-bin	Recycle Bin
/mfa/setup, /mfa/verify	MFA enrollment / verification
/forgot-password, /reset-password/...	Password recovery
Installation & Setup

Development environment: Windows host → Oracle VirtualBox → Ubuntu Server → Flask app on port 5000.

1. Clone and create a virtual environment
bash
cd NAS-Management-System
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
2. Create the MySQL database
sql
CREATE DATABASE nas_management;
CREATE USER 'nas_app'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON nas_management.* TO 'nas_app'@'localhost';
3. Configure .env
env
DB_HOST=localhost
DB_USER=nas_app
DB_PASSWORD=your_password
DB_NAME=nas_management
SECRET_KEY=change_me
MFA_ENCRYPTION_KEY=your_fernet_key   # keep this safe and backed up!
MAIL_USERNAME=your_gmail_address
MAIL_PASSWORD=your_gmail_app_password

Generate a Fernet key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" Losing MFA_ENCRYPTION_KEY makes stored MFA secrets unrecoverable.

4. Run the app
bash
python app.py

Then open http://localhost:5000.

VirtualBox shared folder (for Dropbox backups)

A shared folder is mounted at /media/sf_NAS_Backups (requires the vboxsf module and group membership), which maps to the Windows Dropbox-synced folder.

Public demo access

An ngrok HTTPS tunnel can expose the app for demos. This is not a hardened production deployment.

Backups

Automatic backup flow (scripts/automatic_backup.py):

Ubuntu runs the backup script.
NAS storage files are collected.
MySQL database is dumped.
Files + dump are combined into a compressed archive.
A SHA-256 checksum is calculated.
The archive is copied to the Dropbox shared folder.
Archives older than 30 days are removed.

Schedule: Daily at 2:00 AM Central time via nas-auto-backup.service and nas-auto-backup.timer (systemd).

Tested: archive creation, Dropbox copy, SHA-256 verification, extraction, and restoring a database backup into a separate test database (4 restored user records vs. 4 source records).

Recycle Bin	Backup
Recovers recently deleted files	Disaster recovery for files + database
Individual file restore	Archive/database restore
30-day item retention	30-day archive retention
Security
Feature	Implementation
Password hashing	Werkzeug
Role-based access	Admin and Student roles
MFA	TOTP, QR enrollment, recovery codes
MFA secret encryption	Fernet
Path protection	Safe path validation (prevents traversal)
File permissions	Private / Read / Edit
Sessions	Flask sessions
Password recovery	Hashed, expiring, single-use tokens
CSRF	Custom token on password-reset form only
Backup integrity	SHA-256 checksums
Credentials	Stored in .env

Recommended hardening before real use:

Finish MFA encryption-key recovery
Complete password-reset CSRF and Gmail SMTP tests
Add global CSRF protection on all state-changing forms
Add login rate limiting and account lockout
Configure Secure, HttpOnly and SameSite session cookies
Add antivirus scanning for uploads
Use a production WSGI server (e.g., Gunicorn) behind an HTTPS reverse proxy
Encrypt backup archives
Restrict public access until all security tests pass
Project Status
Developed and demonstrated
Flask + MySQL connection
Registration and login
Dashboard (UMKC LMS Demo branding)
File management and user management
File sharing (Read sharing demonstrated)
Student storage dashboard and quota logic
Recycle Bin (Restore / Delete Forever demonstrated)
Backup to Dropbox, extraction and test restore
Daily backup automation (systemd timer configured)
UMKC-themed UI on login, registration, dashboard and five management pages
Needs final testing or recovery
Feature	Remaining task
MFA	Recover the original MFA_ENCRYPTION_KEY or safely re-enroll the affected account
Gmail password reset	Confirm SMTP authentication and successful delivery
Password-reset CSRF	Resolve token/session mismatch
90% storage email alert	Test real notification delivery
Monitoring API	Retest /api/system-info (earlier 404 observed)
Recycle Bin automation	Confirm systemd cleanup timer is active
30-day expiry	Verify cleanup after an item actually expires
Permission enforcement	Test Read/Edit/Private for students and admin access
Public deployment	Harden before using real student information
Known Issues
MFA: The original MFA_ENCRYPTION_KEY went missing from .env. The one MFA-enabled account's authenticator cannot be assumed usable until the key is restored. MFA is implemented but undergoing key recovery.
Password reset: Gmail SMTP previously had authentication/disconnection issues, and the CSRF token was rejected before the mail step.
Monitoring: /api/system-info returned a 404 in an earlier session.
Future Enhancements
Enhancement	Benefit
Passkey / WebAuthn	Phishing-resistant login
Centralized security dashboard	View security events and account activity
Antivirus scanning	Detect malicious uploads
Encrypted file storage	Protect stored documents
Advanced sharing controls	Expiring access, download restrictions
Version history	Recover earlier document versions
Search	Find files by name, owner or date
Production deployment	More reliable public access
Audit reports	Export student activity reports
Email alerts	Automated storage and security notifications
Disclaimer

UMKC LMS Demo is an unofficial student project created for learning and demonstration purposes. It is not affiliated with or endorsed by the University of Missouri–Kansas City.
