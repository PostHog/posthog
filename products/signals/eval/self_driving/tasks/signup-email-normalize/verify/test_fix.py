# Catches: accounts created with mixed-case emails (as mobile keyboards produce) being unreachable at login and password reset — email handling must be case-insensitive end to end.
import sys
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acme_accounts.accounts import AccountService, EmailTakenError


class TestEmailCaseNormalization(unittest.TestCase):
    def setUp(self):
        self.service = AccountService()

    def test_mixed_case_signup_then_lowercase_login(self):
        self.service.create_user("Ana@Example.com", "hunter2!secret")
        self.assertIsNotNone(self.service.authenticate("ana@example.com", "hunter2!secret"))

    def test_any_casing_logs_in(self):
        self.service.create_user("Ana@Example.com", "hunter2!secret")
        for attempt in ("Ana@Example.com", "ANA@EXAMPLE.COM", "aNa@eXaMpLe.CoM"):
            with self.subTest(attempt=attempt):
                self.assertIsNotNone(self.service.authenticate(attempt, "hunter2!secret"))

    def test_password_reset_finds_mixed_case_account(self):
        self.service.create_user("Ana@Example.com", "hunter2!secret")
        self.assertIsNotNone(self.service.request_password_reset("ana@example.com"))

    def test_same_mailbox_cannot_become_two_accounts(self):
        self.service.create_user("Dana@Example.com", "first-password-1")
        with self.assertRaises(EmailTakenError):
            self.service.create_user("dana@example.com", "second-password-2")


if __name__ == "__main__":
    unittest.main()
