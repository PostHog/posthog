"""Payload for the product opt-in endpoint."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import Enrollment


class EnrollmentSerializer(DataclassSerializer):
    class Meta:
        dataclass = Enrollment
        extra_kwargs = {
            "enabled": {
                "help_text": "Whether this project has enabled engineering analytics, so its warehouse views, "
                "test census and CI failure logs are kept up to date."
            },
        }
