from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("schedule", "0003_bootstrap_schedule_tables"),
        ("schedule", "0003_ensure_schedule_tables_sql"),
        ("schedule", "0003_create_schedule_tables_safely"),
    ]

    operations = []

