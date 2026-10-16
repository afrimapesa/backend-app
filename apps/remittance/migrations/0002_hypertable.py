from django.db import migrations


class Migration(migrations.Migration):
    """Convert provider_quotes into a TimescaleDB hypertable partitioned by observed_at."""

    dependencies = [
        ("core", "0001_timescaledb"),
        ("remittance", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            "SELECT create_hypertable('provider_quotes', by_range('observed_at', INTERVAL '7 days'));",
            # Dropping the table (reversing 0001) removes the hypertable too.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
