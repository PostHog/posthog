from posthog.test.base import BaseTest

from django.core.management import call_command
from django.test import override_settings

from cryptography.fernet import InvalidToken

from posthog.management.commands.reencrypt_flag_payloads import Command

from products.feature_flags.backend.encrypted_flag_payloads import (
    FlagPayloadCodec,
    flag_payload_codec,
    get_decrypted_flag_payload,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

OLD_KEY = "old-flags-secret-key-0123456789abcdefghij"
NEW_KEY = "new-flags-secret-key-0123456789abcdefghij"
PAYLOAD = '"super-secret-config"'


def _codec(key: str) -> FlagPayloadCodec:
    return FlagPayloadCodec.from_keys(key, [], require_min_length=False)


class TestReencryptFlagPayloads(BaseTest):
    def _make_flag(self, key: str, encrypt_with: str, payload: str = PAYLOAD) -> FeatureFlag:
        token = _codec(encrypt_with).encrypt(payload.encode("utf-8")).decode("utf-8")
        return FeatureFlag.objects.create(
            team=self.team,
            key=key,
            created_by=self.user,
            is_remote_configuration=True,
            has_encrypted_payloads=True,
            filters={"groups": [], "payloads": {"true": token}},
        )

    def _run(self, *args: str) -> None:
        call_command("reencrypt_flag_payloads", "--team-id", str(self.team.id), *args)

    def test_live_run_reencrypts_with_new_main_key(self):
        flag = self._make_flag("rc-flag", encrypt_with=OLD_KEY)

        with override_settings(FLAGS_SECRET_KEYS=[NEW_KEY, OLD_KEY]):
            self._run("--live-run")

        flag.refresh_from_db()
        new_token = flag.filters["payloads"]["true"].encode("utf-8")

        # The new key alone now decrypts it, so the old key can be safely dropped.
        assert _codec(NEW_KEY).decrypt(new_token).decode("utf-8") == PAYLOAD
        with self.assertRaises(InvalidToken):
            _codec(OLD_KEY).decrypt(new_token)

    def test_dry_run_leaves_payload_untouched(self):
        flag = self._make_flag("rc-flag", encrypt_with=OLD_KEY)
        original = flag.filters["payloads"]["true"]

        with override_settings(FLAGS_SECRET_KEYS=[NEW_KEY, OLD_KEY]):
            self._run()  # no --live-run

        flag.refresh_from_db()
        assert flag.filters["payloads"]["true"] == original

    def test_skips_flag_no_key_can_decrypt(self):
        # Payload encrypted with a key absent from FLAGS_SECRET_KEYS.
        flag = self._make_flag("rc-flag", encrypt_with="orphan-key-0123456789abcdefghijklmnop")
        original = flag.filters["payloads"]["true"]

        with override_settings(FLAGS_SECRET_KEYS=[NEW_KEY, OLD_KEY]):
            self._run("--live-run")

        flag.refresh_from_db()
        assert flag.filters["payloads"]["true"] == original

    def test_helper_decrypts_after_reencryption(self):
        self._make_flag("rc-flag", encrypt_with=OLD_KEY)

        with override_settings(FLAGS_SECRET_KEYS=[NEW_KEY, OLD_KEY]):
            self._run("--live-run")

            flag = FeatureFlag.objects.get(team=self.team, key="rc-flag")
            token = flag.filters["payloads"]["true"]
            # The production decrypt path (primary key in FLAGS_SECRET_KEYS) reads it back.
            assert get_decrypted_flag_payload(token, should_decrypt=True) == PAYLOAD

    def test_rerun_skips_already_rotated_rows(self):
        self._make_flag("rc-flag", encrypt_with=OLD_KEY)

        with override_settings(FLAGS_SECRET_KEYS=[NEW_KEY, OLD_KEY]):
            self._run("--live-run")
            first = FeatureFlag.objects.get(team=self.team, key="rc-flag").filters["payloads"]["true"]

            # Second pass: payloads already decrypt on the primary key, so nothing is rewritten.
            self._run("--live-run")
            second = FeatureFlag.objects.get(team=self.team, key="rc-flag").filters["payloads"]["true"]

        assert first == second

    def test_reencrypt_re_reads_filters_under_lock(self):
        # The command streams a snapshot of filters, but the live write must merge the
        # rotation into the *current* DB value so a concurrent edit to sibling fields
        # (here "groups") isn't clobbered by writing back the stale streamed blob.
        flag = self._make_flag("rc-flag", encrypt_with=OLD_KEY)
        FeatureFlag.objects.filter(pk=flag.pk).update(
            filters={"groups": [{"properties": [{"key": "x", "value": "y"}]}], "payloads": flag.filters["payloads"]}
        )

        with override_settings(FLAGS_SECRET_KEYS=[NEW_KEY, OLD_KEY]):
            assert Command()._reencrypt(flag.pk, flag_payload_codec()) is True

        flag.refresh_from_db()
        assert flag.filters["groups"] == [{"properties": [{"key": "x", "value": "y"}]}]
        new_token = flag.filters["payloads"]["true"].encode("utf-8")
        assert _codec(NEW_KEY).decrypt(new_token).decode("utf-8") == PAYLOAD
