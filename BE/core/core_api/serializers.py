from rest_framework import serializers
from .models import Task
from users.utils import is_admin


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = "__all__"
        read_only_fields = ("created_by",)

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if not is_admin(self.context["request"].user):
            validated_data.pop("created_by", None)
        return super().update(instance, validated_data)
