from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models import Team

from products.messaging.backend.models.message_template import MessageTemplate


class TestMessageTemplateKey(BaseTest):
    def _create_template(self, team: Team, key: str, deleted: bool = False) -> MessageTemplate:
        return MessageTemplate.objects.create(team=team, name=key, key=key, deleted=deleted)

    def test_a_live_template_holds_its_key_within_its_team(self) -> None:
        self._create_template(self.team, "welcome")

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_template(self.team, "welcome")

    @parameterized.expand(
        [
            ("in_another_team", False, True),
            ("after_the_holder_is_deleted", True, False),
        ]
    )
    def test_the_key_is_free(self, _name: str, first_is_deleted: bool, second_in_other_team: bool) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        self._create_template(self.team, "welcome", deleted=first_is_deleted)

        second = self._create_template(other_team if second_in_other_team else self.team, "welcome")

        self.assertEqual(MessageTemplate.objects.get(pk=second.pk).key, "welcome")
