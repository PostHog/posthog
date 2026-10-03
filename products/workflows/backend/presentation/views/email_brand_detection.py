import re

from rest_framework import serializers, status
from rest_framework.exceptions import APIException

REPOSITORY_FULL_NAME = re.compile(r"^(?!\.+/)[\w.-]+/(?!\.+$)[\w.-]+$")


class GitHubBusyError(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "github_busy"
    default_detail = "GitHub is busy. Try again in a minute."


class RepositoryUnreadableError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "repository_unreadable"
    default_detail = (
        "PostHog can't read this repository. Give the PostHog GitHub App access to it in your GitHub settings."
    )


class EmailBrandDetectRequestSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="Id of the project's GitHub integration to read with.")
    repository = serializers.RegexField(
        REPOSITORY_FULL_NAME,
        max_length=255,
        help_text="Full name of the repository to read, as owner/repo.",
    )
    app_root = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Directory of the app to read inside a monorepo, for example apps/web. "
        "Leave it out to use the likeliest app.",
    )
    refresh = serializers.BooleanField(
        default=False, help_text="Read the repository again instead of reusing a detection from the last 10 minutes."
    )


class EmailBrandCandidateSerializer(serializers.Serializer):
    value = serializers.CharField(help_text="The value: a name, a #rrggbb color or a font family.")
    path = serializers.CharField(
        allow_null=True, help_text="Repository path of the file the value came from. Null for a default value."
    )
    line = serializers.IntegerField(allow_null=True, help_text="1-based line in that file, or null.")
    default_theme = serializers.BooleanField(
        help_text="Whether the color is the untouched default primary of a UI kit theme, rather than a brand choice."
    )
    font_stack = serializers.CharField(
        allow_null=True, help_text="For a font family: a CSS font stack for email that ends in safe fonts."
    )


class EmailBrandProposalSerializer(serializers.Serializer):
    name = EmailBrandCandidateSerializer(allow_null=True, help_text="Proposed brand name.")
    primary_color = EmailBrandCandidateSerializer(allow_null=True, help_text="Proposed primary color, or null.")
    accent_color = EmailBrandCandidateSerializer(allow_null=True, help_text="Proposed accent color, or null.")
    text_color = EmailBrandCandidateSerializer(allow_null=True, help_text="Proposed body text color.")
    background_color = EmailBrandCandidateSerializer(allow_null=True, help_text="Proposed background color.")
    font_family = EmailBrandCandidateSerializer(allow_null=True, help_text="Proposed font family, or null.")


class EmailBrandCandidatesSerializer(serializers.Serializer):
    name = EmailBrandCandidateSerializer(many=True, help_text="Name candidates, best first.")
    primary_color = EmailBrandCandidateSerializer(many=True, help_text="Primary color candidates, best first.")
    accent_color = EmailBrandCandidateSerializer(many=True, help_text="Accent color candidates, best first.")
    text_color = EmailBrandCandidateSerializer(many=True, help_text="Text color candidates, best first.")
    background_color = EmailBrandCandidateSerializer(many=True, help_text="Background color candidates, best first.")
    font_family = EmailBrandCandidateSerializer(many=True, help_text="Font family candidates, best first.")


class EmailBrandFoundValueSerializer(serializers.Serializer):
    field = serializers.CharField(
        help_text="Email brand field the value is a candidate for, for example primary_color."
    )
    value = serializers.CharField(help_text="The value found in the file.")


class EmailBrandFileReadSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="Repository path of a file detection read.")
    found = EmailBrandFoundValueSerializer(many=True, help_text="The brand values that file gave.")


class EmailBrandDetectionSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Full name of the repository that was read.")
    app_root = serializers.CharField(help_text="Directory of the app that was read. Empty for the repository root.")
    app_root_alternatives = serializers.ListField(
        child=serializers.CharField(), help_text="Other app directories of a monorepo, likeliest first."
    )
    proposal = EmailBrandProposalSerializer(help_text="The proposed Email brand. It is not saved.")
    candidates = EmailBrandCandidatesSerializer(help_text="Every distinct value found per field, best first.")
    files_read = EmailBrandFileReadSerializer(many=True, help_text="The files detection read, in reading order.")
