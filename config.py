import mysql.connector
import os, uuid
from dotenv import load_dotenv

load_dotenv()


# Project base directory
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Logical upload directory (no full path stored anywhere else)
UPLOAD_DIR = "uploads"
UPLOAD_FOLDER = os.path.join(BASE_DIR, UPLOAD_DIR)

# Web-accessible base URL for uploads (matches Nginx /python/ prefix)
# BASE_UPLOAD_URL = os.getenv("BASE_UPLOAD_URL", "/python/uploads")
BASE_UPLOAD_URL = os.getenv("BASE_UPLOAD_URL", "/uploads")

# Sub-folders for different file types
UPLOAD_SUBDIRS = {
    "PROFILE_PIC": "profile_pictures",
    "PROJECT_PPRT": "project_pprt",
    "TASK_FILES": "task_files",
    "TRACKER_FILES": "tracker_files",
}

RESET_SECRET_KEY = os.getenv("RESET_SECRET_KEY")
RESET_TOKEN_TTL_SECONDS = int(os.getenv("RESET_TOKEN_TTL_SECONDS", "300"))
RESET_FRONTEND_URL = os.getenv("RESET_FRONTEND_URL", "https://tfshrms.cloud/")

if not RESET_SECRET_KEY:
    raise RuntimeError("RESET_SECRET_KEY is missing")

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),  # Use env var or default to 'localhost'
        port=int(os.getenv("DB_PORT", 3306)),  # Use env var or default to 3306
        user=os.getenv("DB_USERNAME"),  # Use env var or default to 'root'
        password=os.getenv("DB_PASSWORD", ""),  # Use env var or default to empty string
        database=os.getenv(
            "DB_DATABASE", "tfs_hrms"
        ),  # Use env var or default to 'tfs_hrms'
    )

    print("DB USER:", os.getenv("DB_USERNAME"))
    print("DB PASS:", os.getenv("DB_PASSWORD"))
    print("DB NAME:", os.getenv("DB_DATABASE"))
