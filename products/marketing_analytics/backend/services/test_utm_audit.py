from products.marketing_analytics.backend.services.utm_audit import UtmIssueSeverity, _cross_reference


class TestCrossReference:
    def test_campaign_with_matching_utm_events(self):
        campaigns = [
            {
                "campaign_name": "Spring Sale",
                "campaign_id": "123",
                "source_name": "google",
                "spend": 100.0,
                "clicks": 50,
                "impressions": 1000,
            }
        ]
        utm_events = {("spring sale", "google"): 42}

        results = _cross_reference(campaigns, utm_events)

        assert len(results) == 1
        assert results[0].has_utm_events is True
        assert results[0].event_count == 42
        assert len(results[0].issues) == 0

    def test_campaign_with_no_utm_events(self):
        campaigns = [
            {
                "campaign_name": "Summer Promo",
                "campaign_id": "456",
                "source_name": "google",
                "spend": 500.0,
                "clicks": 100,
                "impressions": 5000,
            }
        ]
        utm_events: dict[tuple[str, str], int] = {}

        results = _cross_reference(campaigns, utm_events)

        assert len(results) == 1
        assert results[0].has_utm_events is False
        assert results[0].event_count == 0
        assert len(results[0].issues) == 1
        assert results[0].issues[0].field == "utm_campaign"
        assert results[0].issues[0].severity == UtmIssueSeverity.ERROR

    def test_campaign_with_source_mismatch(self):
        campaigns = [
            {
                "campaign_name": "Brand Campaign",
                "campaign_id": "789",
                "source_name": "google",
                "spend": 200.0,
                "clicks": 80,
                "impressions": 2000,
            }
        ]
        # Events exist for the campaign but with a different source
        utm_events = {("brand campaign", "adwords"): 30}

        results = _cross_reference(campaigns, utm_events)

        assert len(results) == 1
        assert results[0].has_utm_events is False
        assert len(results[0].issues) == 1
        assert results[0].issues[0].field == "utm_source"
        assert results[0].issues[0].severity == UtmIssueSeverity.WARNING

    def test_case_insensitive_matching(self):
        campaigns = [
            {
                "campaign_name": "WINTER Sale",
                "campaign_id": "101",
                "source_name": "Google",
                "spend": 150.0,
                "clicks": 60,
                "impressions": 1500,
            }
        ]
        utm_events = {("winter sale", "google"): 25}

        results = _cross_reference(campaigns, utm_events)

        assert len(results) == 1
        assert results[0].has_utm_events is True
        assert results[0].event_count == 25
        assert len(results[0].issues) == 0

    def test_multiple_campaigns_mixed_issues(self):
        campaigns = [
            {
                "campaign_name": "Good Campaign",
                "campaign_id": "1",
                "source_name": "google",
                "spend": 1000.0,
                "clicks": 500,
                "impressions": 10000,
            },
            {
                "campaign_name": "Bad Campaign",
                "campaign_id": "2",
                "source_name": "meta",
                "spend": 200.0,
                "clicks": 50,
                "impressions": 2000,
            },
            {
                "campaign_name": "Worse Campaign",
                "campaign_id": "3",
                "source_name": "google",
                "spend": 800.0,
                "clicks": 100,
                "impressions": 5000,
            },
        ]
        utm_events = {("good campaign", "google"): 100}

        results = _cross_reference(campaigns, utm_events)

        assert len(results) == 3

        good = next(r for r in results if r.campaign_name == "Good Campaign")
        bad = next(r for r in results if r.campaign_name == "Bad Campaign")
        worse = next(r for r in results if r.campaign_name == "Worse Campaign")

        assert len(good.issues) == 0
        assert good.has_utm_events is True

        assert len(bad.issues) == 1
        assert bad.issues[0].severity == UtmIssueSeverity.ERROR

        assert len(worse.issues) == 1
        assert worse.issues[0].severity == UtmIssueSeverity.ERROR

    def test_empty_campaigns(self):
        results = _cross_reference([], {})
        assert len(results) == 0
