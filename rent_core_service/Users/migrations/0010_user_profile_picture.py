from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Users', '0009_user_subscription_started_at_user_subscription_tier'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='profile_picture',
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
    ]
