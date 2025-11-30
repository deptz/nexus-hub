"""Create agentic_plans table

Revision ID: 008
Revises: 004
Create Date: 2025-01-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Read and execute SQL file
    import os
    sql_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "008_create_agentic_plans.sql"
    )
    
    if os.path.exists(sql_file):
        with open(sql_file, 'r') as f:
            op.execute(f.read())
    
    # Also enable RLS
    rls_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "008_enable_rls_agentic_plans.sql"
    )
    
    if os.path.exists(rls_file):
        with open(rls_file, 'r') as f:
            op.execute(f.read())


def downgrade() -> None:
    # Drop agentic_plans table and related objects
    op.execute("DROP POLICY IF EXISTS agentic_plans_tenant_isolation ON agentic_plans")
    op.execute("DROP TABLE IF EXISTS agentic_plans CASCADE")

