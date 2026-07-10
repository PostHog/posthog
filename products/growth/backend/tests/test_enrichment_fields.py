from products.growth.backend.enrichment.fields import EnrichmentFields


def test_to_dict_drops_unset_fields():
    fields = EnrichmentFields(company_type="startup", headcount=42)
    assert fields.to_dict() == {"company_type": "startup", "headcount": 42}


def test_to_dict_keeps_falsey_but_set_values():
    fields = EnrichmentFields(founded_year=0, is_yc_company=False)
    assert fields.to_dict() == {"founded_year": 0, "is_yc_company": False}


def test_to_group_properties_writes_takeover_fields_on_icp_keys_and_the_rest_prefixed():
    fields = EnrichmentFields(company_type="startup", industry="Fintech", headcount=42, country="US")
    assert fields.to_group_properties() == {
        "enrichment_company_type": "startup",
        "enrichment_industry": "Fintech",
        "icp_employees": 42,
        "icp_country": "US",
    }


def test_empty_fields_produce_empty_dicts():
    fields = EnrichmentFields()
    assert fields.to_dict() == {}
    assert fields.to_group_properties() == {}
