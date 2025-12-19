import sqlite3
import os
from .config import settings


def get_db_connection():
    """Establishes a connection to the SQLite database."""
    db_path = os.path.join(settings.DB_DIR, settings.DB_FILE)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def create_log_table():
    """Creates the log table if it doesn't exist."""
    conn = get_db_connection()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                level TEXT,
                message TEXT
            );
        """
        )
    conn.close()


def init_db():
    """Initializes the database and creates necessary tables."""
    if not os.path.exists(settings.DB_DIR):
        os.makedirs(settings.DB_DIR)
    create_log_table()
