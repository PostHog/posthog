from rest_framework import serializers

from products.wizard.backend.facade.enums import WizardRunEnvironment


class WizardProgramSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True, help_text="Stable identifier used to select the program.")
    name = serializers.CharField(read_only=True, help_text="Display name of the program.")
    description = serializers.CharField(read_only=True, help_text="What the program does.")
    wizard_version = serializers.CharField(
        read_only=True, help_text="Exact Wizard package version used by the program."
    )
    command = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Wizard CLI arguments used to start the program.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Labels that categorize the program.",
    )
    required_programs = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Programs that should run before this program.",
    )
    supported_environments = serializers.ListField(
        child=serializers.ChoiceField(choices=[environment.value for environment in WizardRunEnvironment]),
        read_only=True,
        help_text="Environments where the program can run.",
    )
