
from pathlib import Path
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_DIR / ".env")

from modules.recycle_bin import cleanup_expired_items

if __name__ == "__main__":
    count = cleanup_expired_items()
    print(f"Recycle Bin cleanup completed. Items removed: {count}")
