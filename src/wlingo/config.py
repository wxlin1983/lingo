import os


class Settings:
    PROJECT_NAME: str = "wlingo"
    DEBUG: bool = False
    LOG_DIR: str = "log"
    LOG_FILE: str = "wlingo.log"
    DB_DIR: str = "db"
    DB_FILE: str = "wlingo.db"
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    VOCAB_DIR: str = "vocabulary"
    TEST_SIZE: int = 15
    SESSION_COOKIE_NAME: str = "quiz_session_id"
    SESSION_TIMEOUT_MINUTES: int = 120
    ROOT_PATH: str = os.environ.get("ROOT_PATH", "")


settings = Settings()
