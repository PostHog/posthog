from django.test import SimpleTestCase

from parameterized import parameterized

from products.web_analytics.backend.recap import _build_highlights, compute_persona


def _metric(current, percent=0, direction="Up", previous=None):
    change = {"percent": percent, "direction": direction} if percent else None
    return {"current": current, "previous": previous, "change": change}


def _digest(**overrides):
    base = {
        "visitors": _metric(100),
        "pageviews": _metric(100),
        "sessions": _metric(100),
        "bounce_rate": _metric(40.0),
        "avg_session_duration": {"current": "1m", "previous": None, "change": None},
        "top_pages": [],
        "top_sources": [],
        "goals": [],
    }
    base.update(overrides)
    return base


class TestComputePersona(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "low_traffic_is_just_getting_started",
                _digest(visitors=_metric(10, percent=80, direction="Up")),
                "just_getting_started",
            ),
            (
                "boundary_25_is_not_low_traffic",
                _digest(visitors=_metric(25)),
                "steady_hog",
            ),
            (
                "goals_up_is_conversion_machine",
                _digest(
                    visitors=_metric(100, percent=5, direction="Up"),
                    goals=[{"name": "Signup", "conversions": 50, "change": {"percent": 40, "direction": "Up"}}],
                ),
                "conversion_machine",
            ),
            (
                "visitors_up_30_is_traffic_magnet",
                _digest(visitors=_metric(100, percent=40, direction="Up")),
                "traffic_magnet",
            ),
            (
                "dominant_page_is_crowd_favorite",
                _digest(
                    visitors=_metric(100, percent=5, direction="Up"),
                    top_pages=[{"path": "/", "visitors": 60, "change": None}],
                ),
                "crowd_favorite",
            ),
            (
                "search_engine_source_is_search_hog",
                _digest(
                    visitors=_metric(100, percent=5, direction="Up"),
                    top_pages=[{"path": "/", "visitors": 10, "change": None}],
                    top_sources=[{"name": "google.com", "visitors": 40, "change": None}],
                ),
                "search_hog",
            ),
            (
                "social_source_is_word_of_mouth",
                _digest(
                    visitors=_metric(100, percent=5, direction="Up"),
                    top_pages=[{"path": "/", "visitors": 10, "change": None}],
                    top_sources=[{"name": "twitter.com", "visitors": 10, "change": None}],
                ),
                "word_of_mouth",
            ),
            (
                "high_share_referral_is_word_of_mouth",
                _digest(
                    visitors=_metric(100, percent=5, direction="Up"),
                    top_pages=[{"path": "/", "visitors": 10, "change": None}],
                    top_sources=[{"name": "someblog.com", "visitors": 40, "change": None}],
                ),
                "word_of_mouth",
            ),
            (
                "bounce_down_is_loyal_following",
                _digest(
                    visitors=_metric(100, percent=5, direction="Up"),
                    bounce_rate=_metric(30.0, percent=10, direction="Down"),
                ),
                "loyal_following",
            ),
            (
                "broad_growth_is_rising_star",
                _digest(
                    visitors=_metric(100, percent=5, direction="Up"),
                    pageviews=_metric(100, percent=10, direction="Up"),
                    bounce_rate=_metric(45.0, percent=5, direction="Up"),
                    avg_session_duration={
                        "current": "1m",
                        "previous": "1m",
                        "change": {"percent": 5, "direction": "Down"},
                    },
                ),
                "rising_star",
            ),
            (
                "flat_week_is_steady_hog",
                _digest(visitors=_metric(100)),
                "steady_hog",
            ),
        ]
    )
    def test_persona_assignment(self, _name, digest, expected_id):
        persona = compute_persona(digest)
        assert persona["id"] == expected_id
        assert persona["name"]
        assert persona["emoji"]
        assert persona["blurb"]
        assert "{value}" not in persona["blurb"]
        assert persona["color"].startswith("#")

    def test_dominant_page_share_is_clamped_to_100(self):
        digest = _digest(
            visitors=_metric(100, percent=5, direction="Up"),
            top_pages=[{"path": "/", "visitors": 150, "change": None}],
        )
        persona = compute_persona(digest)
        assert persona["id"] == "crowd_favorite"
        assert "100%" in persona["blurb"]
        assert "150%" not in persona["blurb"]

    def test_direct_traffic_top_source_falls_back_to_direct_label(self):
        digest = _digest(
            visitors=_metric(100, percent=5, direction="Up"),
            top_pages=[{"path": "/", "visitors": 10, "change": None}],
            top_sources=[{"name": "", "visitors": 40, "change": None}],
        )
        persona = compute_persona(digest)
        assert persona["id"] == "word_of_mouth"
        assert "Direct" in persona["blurb"]
        assert "  " not in persona["blurb"]


class TestBuildHighlights(SimpleTestCase):
    def test_empty_digest_has_no_highlights(self):
        assert _build_highlights(_digest(visitors=_metric(0))) == []

    def test_milestone_when_crossing_round_number(self):
        digest = _digest(visitors={"current": 120, "previous": 90, "change": {"percent": 33, "direction": "Up"}})
        highlights = _build_highlights(digest)
        milestone = next(h for h in highlights if h["id"] == "milestone")
        assert "100" in milestone["value"]

    def test_milestone_when_crossing_from_zero_baseline(self):
        digest = _digest(visitors=_metric(120))
        highlights = _build_highlights(digest, compare=True)
        milestone = next(h for h in highlights if h["id"] == "milestone")
        assert "100" in milestone["value"]

    def test_no_milestone_when_compare_disabled(self):
        digest = _digest(visitors=_metric(120))
        assert not any(h["id"] == "milestone" for h in _build_highlights(digest, compare=False))

    def test_rising_page_and_top_source(self):
        digest = _digest(
            top_pages=[
                {"path": "/pricing", "visitors": 50, "change": {"percent": 80, "direction": "Up"}},
                {"path": "/", "visitors": 40, "change": {"percent": 5, "direction": "Up"}},
            ],
            top_sources=[{"name": "google.com", "visitors": 30, "change": None}],
        )
        highlights = _build_highlights(digest)
        rising = next(h for h in highlights if h["id"] == "rising_page")
        assert rising["value"] == "/pricing"
        top_source = next(h for h in highlights if h["id"] == "top_source")
        assert top_source["value"] == "google.com"

    def test_capped_at_three(self):
        digest = _digest(
            visitors={"current": 120, "previous": 90, "change": {"percent": 33, "direction": "Up"}},
            top_pages=[{"path": "/a", "visitors": 50, "change": {"percent": 80, "direction": "Up"}}],
            top_sources=[{"name": "google.com", "visitors": 30, "change": None}],
        )
        assert len(_build_highlights(digest)) <= 3
