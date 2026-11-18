from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_suggestions.backend.facade.contracts import PAYLOAD_VERSION
from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionKind
from products.warehouse_suggestions.backend.logic.payloads import payload_from_json, payload_to_json

from .test_lifecycle import PAYLOADS


class TestPayloadFromJson(SimpleTestCase):
    @parameterized.expand([(kind.value, kind) for kind in WarehouseSuggestionKind])
    def test_ignores_keys_a_newer_release_wrote(self, _name: str, kind: WarehouseSuggestionKind) -> None:
        stored = {**payload_to_json(PAYLOADS[kind]), "written_by_a_newer_release": 1}

        assert payload_from_json(kind, PAYLOAD_VERSION, stored) == PAYLOADS[kind]
