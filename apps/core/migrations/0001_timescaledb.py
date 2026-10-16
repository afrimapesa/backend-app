from django.db import migrations


class Migration(migrations.Migration):
    """Enable TimescaleDB. Hypertable migrations in other apps depend on this."""

    operations = [
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS timescaledb;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
