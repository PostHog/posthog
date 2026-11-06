from products.warehouse_sources.sources.hubspot.settings import ENDPOINTS
from products.warehouse_sources.sources.hubspot.source import HubspotSource


def test_hubspot_ships_canonical_descriptions() -> None:
    descriptions = HubspotSource().get_canonical_descriptions_for_table_prefix("")
    assert "contacts" in descriptions
    assert "email" in descriptions["contacts"]["columns"]


def test_hubspot_canonical_covers_every_synced_endpoint() -> None:
    missing = set(ENDPOINTS) - set(HubspotSource().get_canonical_descriptions())
    assert not missing, f"Hubspot endpoints missing canonical descriptions: {sorted(missing)}"
