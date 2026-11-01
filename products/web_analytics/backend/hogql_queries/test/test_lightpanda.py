import re

import pytest

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS


@pytest.mark.parametrize(
    "user_agent",
    ["Lightpanda/1.0", "Lightpanda/2.3.4", "Lightpanda/10.0", "Mozilla/5.0 (compatible; Lightpanda/1.0)"],
)
def test_lightpanda_is_headless_browser_automation(user_agent):
    pattern = "Lightpanda"
    assert re.search(pattern, user_agent)
    bot = BOT_DEFINITIONS[pattern]
    assert (bot.name, bot.category, bot.traffic_type, bot.operator) == (
        "Lightpanda",
        "headless_browser",
        "Automation",
        "Lightpanda",
    )


@pytest.mark.parametrize(
    "user_agent",
    [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:129.0) Gecko/20100101 Firefox/129.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    ],
)
def test_regular_browsers_do_not_match_lightpanda(user_agent):
    assert not re.search("Lightpanda", user_agent)


@pytest.mark.parametrize("user_agent", ["lightpanda/1.0", "LIGHTPANDA/1.0"])
def test_lightpanda_follows_existing_case_sensitive_backend_matching(user_agent):
    assert not re.search("Lightpanda", user_agent)
