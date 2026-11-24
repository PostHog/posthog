from unittest import mock

from django.test import SimpleTestCase

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from products.warehouse_sources.backend.presentation.views.external_data_schema import (
    ExternalDataSchemaSerializer,
    ExternalDataSchemaViewset,
)

# No module-level `pytestmark = [pytest.mark.django_db]` here, unlike test_external_data_schema.py:
# pytest-django's django_db marker ignores a unittest.TestCase's own `databases` restriction, so it
# would fight this SimpleTestCase's deliberate no-database setup instead of just being a no-op.


class TestExternalDataSchemaIntrospection(SimpleTestCase):
    def test_schema_generation_needs_no_team_context(self) -> None:
        view = ExternalDataSchemaViewset()
        view.request = Request(APIRequestFactory().get("/"))
        view.format_kwarg = None
        view.kwargs = {}

        with mock.patch.object(view, "swagger_fake_view", True, create=True):
            serializer = view.get_serializer()
        assert isinstance(serializer, ExternalDataSchemaSerializer)
        assert "table_id" in serializer.fields
