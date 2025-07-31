from rest_framework import serializers
from .models import Issue


class IssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Issue
        fields = [
            "id",
            "title",
            "description",
            "status",
            "origin_product",
            "position",
            "github_branch",
            "github_pr_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "github_branch", "github_pr_url"]

    def create(self, validated_data):
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)
