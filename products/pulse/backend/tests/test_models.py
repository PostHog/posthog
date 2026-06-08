import re
from datetime import timedelta
from pathlib import Path

import pytest
from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.models.scoping.manager import TeamScopeError

from products.pulse.backend.models import (
    SENSITIVITY_PRESETS,
    DetectionMode,
    PulseDigest,
    PulseDigestStatus,
    PulseFinding,
    PulseSubscription,
    PulseSubscriptionFrequency,
    Sensitivity,
)


class TestPulseEnums:
    def test_detection_mode_values(self):
        assert DetectionMode.CHANGE_V1 == "change_v1"
        assert DetectionMode.DISCOVERY == "discovery"

    def test_sensitivity_values(self):
        assert Sensitivity.CONSERVATIVE == "conservative"
        assert Sensitivity.BALANCED == "balanced"
        assert Sensitivity.SENSITIVE == "sensitive"
        assert Sensitivity.CUSTOM == "custom"

    @pytest.mark.parametrize(
        "sensitivity,expected_min_change_pct,expected_robust_z",
        [
            (Sensitivity.CONSERVATIVE, 0.40, 3.5),
            (Sensitivity.BALANCED, 0.25, 3.5),
            (Sensitivity.SENSITIVE, 0.15, 3.0),
        ],
    )
    def test_sensitivity_presets_resolve(self, sensitivity, expected_min_change_pct, expected_robust_z):
        min_change_pct, robust_z = SENSITIVITY_PRESETS[sensitivity]
        assert min_change_pct == expected_min_change_pct
        assert robust_z == expected_robust_z

    def test_custom_has_no_preset_entry(self):
        assert Sensitivity.CUSTOM not in SENSITIVITY_PRESETS

    def test_frontend_sensitivity_presets_match_backend(self):
        # Single cross-language drift guard: the frontend mirrors SENSITIVITY_PRESETS in utils.ts to
        # apply thresholds locally. Assert the FE values equal the backend source of truth so the two
        # can't silently diverge — independent literal tests on each side would not catch drift.
        utils_ts = (Path(__file__).resolve().parents[2] / "frontend" / "utils.ts").read_text()
        block = utils_ts.split("export const SENSITIVITY_PRESETS", 1)[1].split("\n}", 1)[0]
        frontend = {}
        for name, body in re.findall(r"(conservative|balanced|sensitive):\s*\{([^}]*)\}", block):
            min_change = float(re.search(r"min_change_pct:\s*([\d.]+)", body).group(1))
            robust_z = float(re.search(r"robust_z_threshold:\s*([\d.]+)", body).group(1))
            frontend[name] = (min_change, robust_z)
        assert frontend == {k.value: v for k, v in SENSITIVITY_PRESETS.items()}


def _make_digest(test: BaseTest) -> PulseDigest:
    now = timezone.now()
    with team_scope(test.team.id):
        return PulseDigest.objects.create(
            team=test.team,
            period_start=now - timedelta(days=7),
            period_end=now,
            status=PulseDigestStatus.PENDING,
        )


class TestPulseDigestScoping(BaseTest):
    def test_query_without_team_context_raises(self):
        _make_digest(self)
        with pytest.raises(TeamScopeError, match="No team context set"):
            list(PulseDigest.objects.all())

    def test_query_with_team_scope_filters_to_team(self):
        digest = _make_digest(self)
        with team_scope(self.team.id):
            assert list(PulseDigest.objects.all()) == [digest]

    def test_for_team_scopes_explicitly(self):
        digest = _make_digest(self)
        assert list(PulseDigest.objects.for_team(self.team.id)) == [digest]

    def test_uses_uuid7_id(self):
        # uuid7 ids are version 7; UUIDT (deprecated) is not.
        digest = _make_digest(self)
        assert digest.id.version == 7

    def test_one_digest_per_team_and_period(self):
        now = timezone.now()
        with team_scope(self.team.id):
            PulseDigest.objects.create(
                team=self.team,
                period_start=now - timedelta(days=7),
                period_end=now,
                status=PulseDigestStatus.PENDING,
            )
            with pytest.raises(IntegrityError), transaction.atomic():
                PulseDigest.objects.create(
                    team=self.team,
                    period_start=now - timedelta(days=7),
                    period_end=now,
                    status=PulseDigestStatus.PENDING,
                )


class TestPulseFindingShape(BaseTest):
    def _make_finding(self, digest: PulseDigest) -> PulseFinding:
        with team_scope(self.team.id):
            return PulseFinding.objects.create(
                team=self.team,
                digest=digest,
                metric_descriptor={"label": "Pageviews"},
                current_value=120.0,
                baseline_value=80.0,
                change_pct=0.5,
                impact=4.47,
                robust_z=3.2,
                narrative="Pageviews rose notably.",
            )

    def test_finding_has_team_and_renamed_fields(self):
        field_names = {f.name for f in PulseFinding._meta.get_fields()}
        assert "team" in field_names
        assert "impact" in field_names
        assert "robust_z" in field_names
        assert "z_score" not in field_names

    def test_finding_persists_with_team(self):
        digest = _make_digest(self)
        finding = self._make_finding(digest)
        assert finding.team_id == self.team.id
        assert finding.robust_z == 3.2
        assert finding.impact == 4.47

    def test_finding_query_without_context_raises(self):
        digest = _make_digest(self)
        self._make_finding(digest)
        with pytest.raises(TeamScopeError, match="No team context set"):
            list(PulseFinding.objects.all())

    def test_finding_query_with_scope_filters_to_team(self):
        digest = _make_digest(self)
        finding = self._make_finding(digest)
        with team_scope(self.team.id):
            assert list(PulseFinding.objects.all()) == [finding]


class TestPulseSubscriptionConfig(BaseTest):
    def test_default_config_fields(self):
        with team_scope(self.team.id):
            sub = PulseSubscription.objects.create(team=self.team)
        assert sub.enabled is False
        assert sub.frequency == PulseSubscriptionFrequency.WEEKLY
        assert sub.detection_mode == DetectionMode.CHANGE_V1
        assert sub.sensitivity == Sensitivity.BALANCED
        assert sub.min_change_pct == 0.25
        assert sub.baseline_weeks == 4
        assert sub.max_findings == 5
        assert sub.robust_z_threshold == 3.5

    def test_subscription_scoped_query(self):
        with team_scope(self.team.id):
            sub = PulseSubscription.objects.create(team=self.team)
        with pytest.raises(TeamScopeError, match="No team context set"):
            list(PulseSubscription.objects.all())
        assert list(PulseSubscription.objects.for_team(self.team.id)) == [sub]


class TestResolveSensitivity(BaseTest):
    @parameterized.expand(
        [
            (Sensitivity.CONSERVATIVE, (0.40, 3.5)),
            (Sensitivity.BALANCED, (0.25, 3.5)),
            (Sensitivity.SENSITIVE, (0.15, 3.0)),
        ]
    )
    def test_preset_overrides_model_fields(self, sensitivity, expected):
        with team_scope(self.team.id):
            sub = PulseSubscription.objects.create(
                team=self.team,
                sensitivity=sensitivity,
                min_change_pct=0.99,  # ignored for presets
                robust_z_threshold=99.0,
            )
        assert sub.resolve_sensitivity() == expected

    def test_custom_uses_own_fields(self):
        with team_scope(self.team.id):
            sub = PulseSubscription.objects.create(
                team=self.team,
                sensitivity=Sensitivity.CUSTOM,
                min_change_pct=0.33,
                robust_z_threshold=2.5,
            )
        assert sub.resolve_sensitivity() == (0.33, 2.5)
