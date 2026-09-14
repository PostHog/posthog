import uuid

import pytest

from products.security.backend.facade.enums import TargetType
from products.security.backend.logic.targets import TARGETS, InvalidTarget, Subject

ORG_ID = str(uuid.UUID(int=7))


class TestNormalize:
    @pytest.mark.parametrize(
        "target_type,raw,expected",
        [
            (TargetType.EMAIL_ROOT, "Farm.Bot+7@Example.com", "farm.bot@example.com"),
            (TargetType.EMAIL_ROOT, "sample.user+x@gmail.com", "sampleuser@gmail.com"),
            (TargetType.EMAIL_ROOT, "sample.user@googlemail.com", "sampleuser@gmail.com"),
            (TargetType.EMAIL, " Name@Example.COM ", "name@example.com"),
            (TargetType.EMAIL_DOMAIN, "@Example.com", "example.com"),
            (TargetType.IP, "198.51.100.7", "198.51.100.7/32"),
            # Host bits inside a range are dropped, so equal ranges store equal values.
            (TargetType.IP, "203.0.113.9/24", "203.0.113.0/24"),
            (TargetType.IP, "2001:db8::1/48", "2001:db8::/48"),
            (TargetType.TEAM_ID, " 042 ", "42"),
        ],
    )
    def test_stores_one_canonical_value(self, target_type, raw, expected):
        assert TARGETS[target_type].normalize(raw) == expected

    @pytest.mark.parametrize(
        "target_type,raw",
        [
            (TargetType.EMAIL, "no-at-sign"),
            (TargetType.EMAIL_ROOT, "+tag@example.com"),
            (TargetType.EMAIL_DOMAIN, "https://example.com/path"),
            (TargetType.IP, "not-an-ip"),
            (TargetType.USER_UUID, "123"),
            (TargetType.TEAM_ID, "0"),
        ],
    )
    def test_refuses_a_value_that_could_never_match(self, target_type, raw):
        with pytest.raises(InvalidTarget):
            TARGETS[target_type].normalize(raw)


class TestMatches:
    @pytest.mark.parametrize(
        "target_type,value,subject,expected",
        [
            (TargetType.EMAIL_ROOT, "farm.bot@example.com", Subject.for_account(email="Farm.Bot+99@example.com"), True),
            (TargetType.EMAIL_ROOT, "farm.bot@example.com", Subject.for_account(email="farmbot@example.com"), False),
            (TargetType.EMAIL_ROOT, "sampleuser@gmail.com", Subject.for_account(email="s.ample.user@gmail.com"), True),
            (TargetType.EMAIL_DOMAIN, "example.com", Subject.for_account(email="a@mail.example.com"), True),
            # A shared suffix is not a subdomain.
            (TargetType.EMAIL_DOMAIN, "example.com", Subject.for_account(email="a@notexample.com"), False),
            (TargetType.EMAIL_DOMAIN, "example.com", Subject(domain="example.com"), True),
            (TargetType.IP, "203.0.113.0/24", Subject(ip="203.0.113.200"), True),
            (TargetType.IP, "203.0.113.0/24", Subject(ip="203.0.114.1"), False),
            (TargetType.IP, "203.0.113.0/24", Subject(ip="2001:db8::1"), False),
            (TargetType.IP, "203.0.113.0/24", Subject(ip="unknown"), False),
            (TargetType.ORGANIZATION_ID, ORG_ID, Subject(organization_ids=frozenset({ORG_ID})), True),
            (TargetType.EMAIL, "a@example.com", Subject(ip="203.0.113.1"), False),
        ],
    )
    def test_matches_only_what_the_target_names(self, target_type, value, subject, expected):
        assert TARGETS[target_type].matches(value, subject) is expected
