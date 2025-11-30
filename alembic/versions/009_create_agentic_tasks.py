"""Create agentic_tasks table

Revision ID: 009
Revises: 008
Create Date: 2025-01-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Read and execute SQL file
    import os
    sql_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "009_create_agentic_tasks.sql"
    )
    
    if os.path.exists(sql_file):
        with open(sql_file, 'r') as f:
            op.execute(f.read())
    
    # Also enable RLS
    rls_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "009_enable_rls_agentic_tasks.sql"
    )
    
    if os.path.exists(rls_file):
        with open(rls_file, 'r') as f:
            op.execute(f.read())


def downgrade() -> None:
    # Drop agentic_tasks table and related objects
    op.execute("DROP POLICY IF EXISTS agentic_tasks_tenant_isolation ON agentic_tasks")
    op.execute("DROP TABLE IF EXISTS agentic_tasks CASCADE")

