from django.db import migrations


def seed_platform_fee(apps, schema_editor):
    SystemConfig = apps.get_model('Admin', 'SystemConfig')
    SystemConfig.objects.get_or_create(
        key='platform_fee_percentage',
        defaults={'value': '10'},
    )
    # Also ensure subscription_price exists in case the shell seed was skipped
    SystemConfig.objects.get_or_create(
        key='subscription_price',
        defaults={'value': '15000'},
    )


def reverse_seed(apps, schema_editor):
    SystemConfig = apps.get_model('Admin', 'SystemConfig')
    SystemConfig.objects.filter(key='platform_fee_percentage').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('Admin', '0002_add_system_config'),
    ]

    operations = [
        migrations.RunPython(seed_platform_fee, reverse_seed),
    ]
