"""Create api_keys table

Revision ID: 004
Revises: 001
Create Date: 2025-01-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '001'  # Update this to the latest revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Read and execute SQL file
    import os
    sql_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "004_create_api_keys_table.sql"
    )
    
    if os.path.exists(sql_file):
        with open(sql_file, 'r') as f:
            op.execute(f.read())


def downgrade() -> None:
    # Drop api_keys table and related objects
    op.execute("DROP POLICY IF EXISTS api_keys_tenant_isolation ON api_keys")
    op.execute("DROP TABLE IF EXISTS api_keys CASCADE")

