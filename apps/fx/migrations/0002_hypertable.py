from django.db import migrations


class Migration(migrations.Migration):
    """Convert fx_mid_rates into a TimescaleDB hypertable partitioned by observed_at."""

    dependencies = [
        ("core", "0001_timescaledb"),
        ("fx", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            "SELECT create_hypertable('fx_mid_rates', by_range('observed_at', INTERVAL '7 days'));",
            # Dropping the table (reversing 0001) removes the hypertable too.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
