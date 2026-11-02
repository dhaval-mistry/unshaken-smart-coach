"""${message}"""
from alembic import op
import sqlalchemy as sa
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = None
depends_on = None

def upgrade():
    """Apply this versioned database change."""
    ${upgrades if upgrades else "pass"}

def downgrade():
    """Reverse only on explicitly approved disposable data."""
    ${downgrades if downgrades else "pass"}
