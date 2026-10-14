"""Entry point for the web server:  uvicorn app.main:app"""

from __future__ import annotations

import logging

from .api import create_app
from .config import load_settings
from .db import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = load_settings()
database = Database(settings.database_url, max_size=settings.db_pool_size)
app = create_app(settings, database)
