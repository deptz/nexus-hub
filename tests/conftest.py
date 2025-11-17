"""Pytest configuration and fixtures."""

import pytest
import os
from dotenv import load_dotenv

# Load test environment variables
load_dotenv()

# Set test environment
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEBUG", "true")

