# Catches: regressions in pre-existing account behavior — same-case login roundtrip, wrong-password rejection, distinct accounts staying distinct, duplicate signups, and reset for unknown emails.
import sys
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acme_accounts.accounts import AccountService, EmailTakenError


class TestAccountBasics(unittest.TestCase):
    def setUp(self):
        self.service = AccountService()

    def test_same_case_signup_and_login_roundtrip(self):
        self.service.create_user("bob@example.com", "correct-horse-1")
        self.assertIsNotNone(self.service.authenticate("bob@example.com", "correct-horse-1"))

    def test_wrong_password_is_rejected(self):
        self.service.create_user("bob@example.com", "correct-horse-1")
        self.assertIsNone(self.service.authenticate("bob@example.com", "wrong-password"))

    def test_unknown_email_is_rejected(self):
        self.assertIsNone(self.service.authenticate("nobody@example.com", "whatever-1"))

    def test_distinct_emails_stay_distinct(self):
        self.service.create_user("ana@example.com", "ana-password-1")
        self.service.create_user("bob@example.com", "bob-password-1")
        self.assertIsNotNone(self.service.authenticate("ana@example.com", "ana-password-1"))
        self.assertIsNone(self.service.authenticate("ana@example.com", "bob-password-1"))
        self.assertIsNotNone(self.service.authenticate("bob@example.com", "bob-password-1"))
        self.assertIsNone(self.service.authenticate("bob@example.com", "ana-password-1"))

    def test_duplicate_signup_same_case_raises(self):
        self.service.create_user("carol@example.com", "carol-password-1")
        with self.assertRaises(EmailTakenError):
            self.service.create_user("carol@example.com", "another-password-2")

    def test_reset_for_unknown_email_returns_none(self):
        self.assertIsNone(self.service.request_password_reset("ghost@example.com"))


if __name__ == "__main__":
    unittest.main()
