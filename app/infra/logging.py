"""Structured logging configuration."""

import logging
import sys
from pythonjsonlogger import jsonlogger
from app.infra.config import config


def setup_logging():
    """Setup structured JSON logging."""
    # Create logger
    logger = logging.getLogger("app")
    logger.setLevel(logging.DEBUG if config.DEBUG else logging.INFO)
    
    # Remove existing handlers
    logger.handlers = []
    
    # Create JSON formatter
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Set levels for third-party loggers
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    
    return logger


# Initialize logging
app_logger = setup_logging()

