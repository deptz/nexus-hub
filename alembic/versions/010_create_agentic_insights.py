"""Create agentic_insights table

Revision ID: 010
Revises: 009
Create Date: 2025-01-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Read and execute SQL file
    import os
    sql_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "010_create_agentic_insights.sql"
    )
    
    if os.path.exists(sql_file):
        with open(sql_file, 'r') as f:
            op.execute(f.read())
    
    # Also enable RLS
    rls_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "010_enable_rls_agentic_insights.sql"
    )
    
    if os.path.exists(rls_file):
        with open(rls_file, 'r') as f:
            op.execute(f.read())


def downgrade() -> None:
    # Drop agentic_insights table and related objects
    op.execute("DROP POLICY IF EXISTS agentic_insights_tenant_isolation ON agentic_insights")
    op.execute("DROP TABLE IF EXISTS agentic_insights CASCADE")

