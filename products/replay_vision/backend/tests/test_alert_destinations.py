from products.alerts.backend.destination_configs import slack_blocks
from products.replay_vision.backend.alert_destinations import EVENT_KIND_CONFIG


def test_match_action_links_to_the_first_observation() -> None:
    action = slack_blocks(EVENT_KIND_CONFIG["match"], ())[-1]["elements"][0]

    assert action["url"] == "{project.url}/replay-vision/observations/{event.properties.observation_ids[1]}"
    assert action["text"]["text"] == "View observation"
