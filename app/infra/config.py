"""Configuration management with secrets support."""

import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
# This ensures dotenv works regardless of where the script is run from
project_root = Path(__file__).parent.parent.parent
env_file = project_root / ".env"

# Load environment variables from .env file
# override=True means existing environment variables take precedence
load_dotenv(dotenv_path=env_file, override=False)

# Import secrets manager (after dotenv loads env vars)
# Use lazy import to avoid circular dependencies
def get_secret_lazy(secret_ref: str, fallback: Optional[str] = None) -> Optional[str]:
    """Lazy import of get_secret to avoid circular dependencies."""
    from app.infra.secrets import get_secret
    return get_secret(secret_ref, fallback)


class Config:
    """Application configuration with secrets management."""
    # Database
    DATABASE_URL: str = get_secret_lazy(
        os.getenv("DATABASE_URL_REF", ""),
        fallback=os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/nexus_hub"
        )
    )
    
    # OpenAI - support vault:// or aws:// references
    OPENAI_API_KEY: Optional[str] = get_secret_lazy(
        os.getenv("OPENAI_API_KEY_REF", ""),
        fallback=os.getenv("OPENAI_API_KEY")
    )
    
    # Gemini - support vault:// or aws:// references
    GEMINI_API_KEY: Optional[str] = get_secret_lazy(
        os.getenv("GEMINI_API_KEY_REF", ""),
        fallback=os.getenv("GEMINI_API_KEY")
    )
    
    # Redis
    REDIS_URL: str = get_secret_lazy(
        os.getenv("REDIS_URL_REF", ""),
        fallback=os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    
    # Application
    APP_ENV: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    # Vault configuration (optional)
    VAULT_ADDR: Optional[str] = os.getenv("VAULT_ADDR")
    VAULT_TOKEN: Optional[str] = os.getenv("VAULT_TOKEN")
    
    # AWS configuration (optional)
    AWS_REGION: Optional[str] = os.getenv("AWS_REGION")
    
    # Telegram Bot configuration (optional)
    TELEGRAM_BOT_TOKEN: Optional[str] = get_secret_lazy(
        os.getenv("TELEGRAM_BOT_TOKEN_REF", ""),
        fallback=os.getenv("TELEGRAM_BOT_TOKEN")
    )
    TELEGRAM_DEFAULT_TENANT_ID: Optional[str] = os.getenv("TELEGRAM_DEFAULT_TENANT_ID")


config = Config()

