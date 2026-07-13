"""Account lifecycle: signup, login, password reset."""

from acme_accounts import analytics
from acme_accounts.passwords import hash_password, verify_password
from acme_accounts.store import UserStore
from acme_accounts.tokens import issue_reset_token


class EmailTakenError(Exception):
    pass


class AccountService:
    def __init__(self, store: UserStore | None = None) -> None:
        self._store = store or UserStore()

    def create_user(self, email: str, password: str) -> dict:
        email = email.strip()
        if self._store.get(email) is not None:
            raise EmailTakenError(email)
        record = {"email": email, "password": hash_password(password)}
        self._store.put(email, record)
        analytics.capture(email, "user_signed_up", {})
        return {"email": record["email"]}

    def authenticate(self, email: str, password: str) -> dict | None:
        email = email.strip().lower()
        record = self._store.get(email)
        if record is None or not verify_password(password, record["password"]):
            analytics.capture(email, "login_failed", {"reason": "invalid_credentials"})
            return None
        analytics.capture(email, "login_succeeded", {})
        return {"email": record["email"]}

    def request_password_reset(self, email: str) -> str | None:
        email = email.strip().lower()
        record = self._store.get(email)
        if record is None:
            analytics.capture(email, "password_reset_failed", {"reason": "account_not_found"})
            return None
        token = issue_reset_token(record["email"])
        analytics.capture(email, "password_reset_requested", {})
        return token
