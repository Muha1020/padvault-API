from rest_framework import serializers
from .models import PushSubscription, Notification

class PushSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushSubscription
        fields = ['endpoint', 'auth', 'p256dh']

    def create(self, validated_data):
        user = self.context['request'].user
        subscription, created = PushSubscription.objects.update_or_create(
            endpoint=validated_data.get('endpoint'),
            defaults={
                'user': user,
                'auth': validated_data.get('auth'),
                'p256dh': validated_data.get('p256dh')
            }
        )
        return subscription

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'
