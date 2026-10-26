from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from parameterized import parameterized

from products.slack_app.backend.logic.interview_recruitment import booking_link, parse_campaign

BOOKING_URL = "https://cal.example.com/team/slack-app"


class TestInterviewCampaign(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain_http", {"message": "Chat with us?", "booking_url": "http://cal.example.com/x"}),
            ("javascript_scheme", {"message": "Chat with us?", "booking_url": "javascript:alert(1)"}),
            ("blank_message", {"message": "   ", "booking_url": BOOKING_URL}),
            ("missing_url", {"message": "Chat with us?"}),
            ("not_json", "{not json"),
            ("no_payload", None),
        ]
    )
    def test_an_unusable_payload_turns_the_invitation_off(self, _name, payload):
        assert parse_campaign("slack-research", payload) is None

    @parameterized.expand([("variant", "slack-q4", "slack-q4"), ("boolean_rollout", None, "slack-research")])
    def test_the_campaign_id_comes_from_the_variant(self, _name, variant, campaign_id):
        campaign = parse_campaign(variant, '{"message": "Chat with us?", "booking_url": "' + BOOKING_URL + '"}')

        assert campaign is not None
        assert campaign.campaign_id == campaign_id
        assert campaign.min_interactions == 3

    def test_the_booking_link_keeps_its_own_query_and_adds_the_attribution(self):
        campaign = parse_campaign("slack-q4", {"message": "Chat?", "booking_url": f"{BOOKING_URL}?duration=30"})
        assert campaign is not None

        link = urlsplit(booking_link(campaign, "bad_rating_modal", "inv-1"))

        assert f"{link.scheme}://{link.netloc}{link.path}" == BOOKING_URL
        assert parse_qs(link.query) == {
            "duration": ["30"],
            "metadata[campaign_id]": ["slack-q4"],
            "metadata[surface]": ["bad_rating_modal"],
            "metadata[invitation_id]": ["inv-1"],
        }
