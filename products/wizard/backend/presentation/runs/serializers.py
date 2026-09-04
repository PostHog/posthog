from collections.abc import Mapping
from typing import cast

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    GitRepositoryWorkspace,
    LocalFolderWorkspace,
    WizardWorkspace,
)
from products.wizard.backend.facade.enums import (
    WizardRunEnvironment,
    WizardRunErrorCode,
    WizardRunStage,
    WizardRunStatus,
    WizardWorkspaceType,
)
from products.wizard.backend.facade.errors import InvalidRepositoryError
from products.wizard.backend.facade.validation import is_wizard_error_code
from products.wizard.backend.presentation.registry.serializers import WizardProgramSerializer


class WizardWorkspaceTypeField(serializers.CharField):
    workspace_type: WizardWorkspaceType

    def to_internal_value(self, data: object) -> str:
        value = super().to_internal_value(cast(str, data))
        if value != self.workspace_type.value:
            self.fail("invalid")
        return value


@extend_schema_field({"type": "string", "const": WizardWorkspaceType.LOCAL_FOLDER.value})
class LocalFolderWorkspaceTypeField(WizardWorkspaceTypeField):
    workspace_type = WizardWorkspaceType.LOCAL_FOLDER


@extend_schema_field({"type": "string", "const": WizardWorkspaceType.GIT_REPOSITORY.value})
class GitRepositoryWorkspaceTypeField(WizardWorkspaceTypeField):
    workspace_type = WizardWorkspaceType.GIT_REPOSITORY


class LocalFolderWorkspaceSerializer(serializers.Serializer):
    type = LocalFolderWorkspaceTypeField(
        help_text="Selects a folder on the user's machine as the workspace.",
    )
    project_name = serializers.CharField(
        allow_blank=False,
        max_length=255,
        help_text="Name of the project in the local folder.",
    )


class GitRepositoryWorkspaceSerializer(serializers.Serializer):
    type = GitRepositoryWorkspaceTypeField(
        help_text="Selects a GitHub repository as the workspace.",
    )
    repository = serializers.CharField(
        allow_blank=False,
        max_length=255,
        help_text="GitHub repository in owner/name format.",
    )

    def validate_repository(self, value: str) -> str:
        repository = value.strip()
        try:
            wizard_facade.validate_git_repository(repository)
        except InvalidRepositoryError:
            raise serializers.ValidationError("Enter a repository in owner/name format.")
        return repository


WizardWorkspaceSchema = PolymorphicProxySerializer(
    component_name="WizardWorkspace",
    serializers={
        WizardWorkspaceType.LOCAL_FOLDER.value: LocalFolderWorkspaceSerializer,
        WizardWorkspaceType.GIT_REPOSITORY.value: GitRepositoryWorkspaceSerializer,
    },
    resource_type_field_name="type",
)


@extend_schema_field(WizardWorkspaceSchema)
class WizardWorkspaceField(serializers.Field):
    def to_internal_value(self, data: object) -> WizardWorkspace:
        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Enter a workspace object.")

        workspace_data = cast(Mapping[str, object], data)
        workspace_type = workspace_data.get("type")
        if workspace_type == WizardWorkspaceType.LOCAL_FOLDER.value:
            local_serializer = LocalFolderWorkspaceSerializer(data=workspace_data)
            local_serializer.is_valid(raise_exception=True)
            return LocalFolderWorkspace(project_name=cast(str, local_serializer.validated_data["project_name"]))
        if workspace_type == WizardWorkspaceType.GIT_REPOSITORY.value:
            repository_serializer = GitRepositoryWorkspaceSerializer(data=workspace_data)
            repository_serializer.is_valid(raise_exception=True)
            return GitRepositoryWorkspace(repository=cast(str, repository_serializer.validated_data["repository"]))
        if "type" not in workspace_data:
            raise serializers.ValidationError({"type": ["This field is required."]})
        raise serializers.ValidationError({"type": ["Select a valid workspace type."]})

    def to_representation(self, value: WizardWorkspace) -> dict[str, object]:
        if isinstance(value, LocalFolderWorkspace):
            return cast(dict[str, object], LocalFolderWorkspaceSerializer(value).data)
        if isinstance(value, GitRepositoryWorkspace):
            return cast(dict[str, object], GitRepositoryWorkspaceSerializer(value).data)
        raise TypeError("Unsupported Wizard workspace")


class WizardRunCreateRequestSerializer(serializers.Serializer):
    program_id = serializers.RegexField(
        regex=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        help_text="Registry program to run.",
    )
    environment = serializers.ChoiceField(
        choices=[environment.value for environment in WizardRunEnvironment],
        help_text="Where the setup agent runs.",
    )
    workspace = WizardWorkspaceField(
        help_text="Project that the setup agent works on.",
    )
    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=255,
        help_text="Unique key that makes cloud run creation safe to retry.",
    )
    wizard_version = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Wizard package version to run. Defaults to the backend pin and accepts latest explicitly.",
    )

    def validate_wizard_version(self, value: str) -> str:
        try:
            return wizard_facade.validate_wizard_version(value)
        except ValueError:
            raise serializers.ValidationError("Enter an exact semantic version or latest.")

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs.get("environment") == WizardRunEnvironment.CLOUD.value and not attrs.get("idempotency_key"):
            raise serializers.ValidationError({"idempotency_key": "This field is required for cloud runs."})
        return attrs

    def to_contract(self, *, team_id: int, created_by_id: int) -> CreateWizardRunInput:
        return CreateWizardRunInput(
            team_id=team_id,
            created_by_id=created_by_id,
            environment=WizardRunEnvironment(cast(str, self.validated_data["environment"])),
            workspace=cast(WizardWorkspace, self.validated_data["workspace"]),
            program_id=cast(str, self.validated_data["program_id"]),
            wizard_version=cast(str | None, self.validated_data.get("wizard_version")),
            idempotency_key=cast(str | None, self.validated_data.get("idempotency_key")),
        )


class WizardRunStatusUpdateRequestSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[
            WizardRunStatus.COMPLETED.value,
            WizardRunStatus.FAILED.value,
            WizardRunStatus.CANCELLED.value,
        ],
        help_text="New terminal status for the Wizard run.",
    )
    error_code = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=50,
        help_text="Machine-readable reason the Wizard run failed.",
    )

    def validate_error_code(self, value: str | None) -> str | None:
        if value is None or is_wizard_error_code(value):
            return value
        try:
            WizardRunErrorCode(value)
        except ValueError as error:
            raise serializers.ValidationError("Enter a valid Wizard run error code.") from error
        return value

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs.get("error_code") is not None and attrs["status"] != WizardRunStatus.FAILED.value:
            raise serializers.ValidationError({"error_code": "Only failed runs can have an error code."})
        return attrs

    def to_status(self) -> WizardRunStatus:
        return WizardRunStatus(cast(str, self.validated_data["status"]))

    def to_error_code(self) -> str | None:
        return cast(str | None, self.validated_data.get("error_code"))


class WizardRunSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique ID of the Wizard run.")
    team_id = serializers.IntegerField(read_only=True, help_text="Project that owns the Wizard run.")
    created_by_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="User who created the Wizard run, or null if that user no longer exists.",
    )
    environment = serializers.ChoiceField(
        read_only=True,
        choices=[environment.value for environment in WizardRunEnvironment],
        help_text="Where the setup agent runs.",
    )
    workspace = WizardWorkspaceField(read_only=True, help_text="Project that the setup agent works on.")
    program = WizardProgramSerializer(read_only=True, help_text="Registry program selected for this run.")
    status = serializers.ChoiceField(
        read_only=True,
        choices=[run_status.value for run_status in WizardRunStatus],
        help_text="Current lifecycle status of the Wizard run.",
    )
    error_code = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Machine-readable failure reason, or null if the run has not failed.",
    )
    error_message = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Safe failure explanation, or null if the run has not failed.",
    )
    stage = serializers.ChoiceField(
        read_only=True,
        allow_null=True,
        choices=[stage.value for stage in WizardRunStage],
        help_text="Current cloud worker stage, or null outside active cloud execution.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the Wizard run was created.")
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="When the run last changed.")
    started_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When execution started, or null while queued.",
    )
    finished_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When execution reached a terminal status, or null while active.",
    )
    deadline_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Cloud execution deadline, or null for local runs.",
    )


class WizardRunErrorSerializer(serializers.Serializer):
    type = serializers.CharField(read_only=True, help_text="Error category.")
    code = serializers.CharField(read_only=True, help_text="Machine-readable error code.")
    detail = serializers.CharField(read_only=True, help_text="What happened and how to continue.")
    attr = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Request field associated with the error, when available.",
    )
