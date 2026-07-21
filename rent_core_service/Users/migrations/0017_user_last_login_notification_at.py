from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Users', '0016_user_admin_level_supportmessage'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='last_login_notification_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
