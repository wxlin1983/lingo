from fastapi.templating import Jinja2Templates

from .config import settings
from .vocabulary import VocabularyManager

templates = Jinja2Templates(directory="templates")
vocab_manager = VocabularyManager(f"{settings.VOCAB_DIR}")
