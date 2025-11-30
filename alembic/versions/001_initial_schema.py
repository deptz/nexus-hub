"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2025-01-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Note: This migration references the SQL files
    # For now, we'll keep using SQL files and reference them
    # In production, you'd convert these to Alembic operations
    
    # Read and execute SQL file
    import os
    sql_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "001_initial_schema.sql"
    )
    
    if os.path.exists(sql_file):
        with open(sql_file, 'r') as f:
            op.execute(f.read())


def downgrade() -> None:
    # Drop all tables (be careful in production!)
    op.execute("DROP SCHEMA IF EXISTS public CASCADE")
    op.execute("CREATE SCHEMA public")


