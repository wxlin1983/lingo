import logging
import sqlite3
from .database import get_db_connection


class SQLiteHandler(logging.Handler):
    """
    A logging handler that writes logs to an SQLite database.
    """

    def __init__(self):
        super().__init__()

    def emit(self, record):
        try:
            conn = get_db_connection()
            with conn:
                conn.execute(
                    "INSERT INTO logs (level, message) VALUES (?, ?)",
                    (record.levelname, self.format(record)),
                )
            conn.close()
        except Exception:
            self.handleError(record)
