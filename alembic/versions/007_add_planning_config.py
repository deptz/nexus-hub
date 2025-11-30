"""Add planning configuration to tenants table

Revision ID: 007
Revises: 004
Create Date: 2025-01-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Read and execute SQL file
    import os
    sql_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "007_add_planning_config.sql"
    )
    
    if os.path.exists(sql_file):
        with open(sql_file, 'r') as f:
            op.execute(f.read())


def downgrade() -> None:
    # Remove columns from tenants table
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS plan_timeout_seconds")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS planning_enabled")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS max_tool_steps")

