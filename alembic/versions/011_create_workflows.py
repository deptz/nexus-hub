"""Create workflow_definitions table

Revision ID: 011
Revises: 010
Create Date: 2025-01-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Read and execute SQL file
    import os
    sql_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "011_create_workflows.sql"
    )
    
    if os.path.exists(sql_file):
        with open(sql_file, 'r') as f:
            op.execute(f.read())
    
    # Also enable RLS
    rls_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "migrations",
        "011_enable_rls_workflows.sql"
    )
    
    if os.path.exists(rls_file):
        with open(rls_file, 'r') as f:
            op.execute(f.read())


def downgrade() -> None:
    # Drop workflow_definitions table and related objects
    op.execute("DROP POLICY IF EXISTS workflow_definitions_tenant_isolation ON workflow_definitions")
    op.execute("DROP TABLE IF EXISTS workflow_definitions CASCADE")

