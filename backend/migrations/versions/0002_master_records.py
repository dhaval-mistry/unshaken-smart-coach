"""Install stable category and body-part master records without overwriting data."""
import os
import sqlalchemy as sa
from alembic import op

revision = "0002_master_records"
down_revision = "0001_database_foundation"
branch_labels = None
depends_on = None
CATEGORIES = [(1,"Barbell","reps"),(2,"Dumbbell","reps"),(3,"Machine/Other","reps"),
              (4,"Bodyweight","reps"),(5,"Assisted Bodyweight","reps"),(6,"Reps Only","reps"),
              (7,"Cardio","duration_distance"),(8,"Duration","duration")]
PARTS = ["None","Arms","Back","Cardio","Chest","Core","Full Body","Legs","Olympic","Other","Shoulders"]


def seed_rows():
    """Return the immutable version-one seed mapping; IDs are not display-order logic."""
    return [("exercise_categories", dict(id=i,name=n,sort_order=i,measurement_kind=k,is_active=True))
            for i,n,k in CATEGORIES] + [("body_parts",dict(id=i,name=n,sort_order=i,is_active=True))
            for i,n in enumerate(PARTS,1)]


def upgrade():
    """Check all conflicts before inserting; never renumber or overwrite records."""
    bind = op.get_bind()
    for table, row in seed_rows():
        found = bind.execute(sa.text(f"SELECT * FROM {table} WHERE id=:id OR name=:name OR sort_order=:sort_order"),row).mappings().all()
        if found and (len(found)!=1 or dict(found[0])!=row):
            raise RuntimeError(f"Master-record conflict in {table}; existing data was not overwritten.")
    for table, row in seed_rows():
        columns = ", ".join(row)
        values = ", ".join(":"+key for key in row)
        bind.execute(sa.text(f"INSERT INTO {table} ({columns}) VALUES ({values}) ON CONFLICT (id) DO NOTHING"),row)


def downgrade():
    """Remove only exact seed rows, only on explicitly authorized disposable data."""
    bind=op.get_bind()
    name=bind.exec_driver_sql("SELECT current_database()").scalar_one()
    if os.environ.get("USC_ALLOW_DISPOSABLE_DOWNGRADE")!="1" or not name.startswith("unshaken_foundation_test_"):
        raise RuntimeError("Rollback is allowed only on explicitly authorized disposable data.")
    for table,row in reversed(seed_rows()):
        conditions=" AND ".join(key+"=:"+key for key in row)
        bind.execute(sa.text(f"DELETE FROM {table} WHERE {conditions}"),row)
