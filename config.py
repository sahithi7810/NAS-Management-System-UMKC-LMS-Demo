import os
class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret")
    DB_HOST = "localhost"
    DB_USER = "nas_app"
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_NAME = "nas_management"

