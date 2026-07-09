from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.presentation.serializers import TaskRunLivingArtifactCreateRequestSerializer


class TestTaskRunLivingArtifactCreateRequestSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("blank_content", {"name": "canvas", "content": ""}, True),
            ("content_and_source", {"name": "canvas", "content": "hi", "source_artifact_id": "artifact-1"}, False),
        ]
    )
    def test_content_source_exclusivity(self, _name: str, data: dict, expected_valid: bool) -> None:
        serializer = TaskRunLivingArtifactCreateRequestSerializer(data=data)
        assert serializer.is_valid() is expected_valid
