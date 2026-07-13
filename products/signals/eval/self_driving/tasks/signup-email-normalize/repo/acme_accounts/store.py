"""In-memory user store. Production swaps this for Postgres behind the same interface."""


class UserStore:
    def __init__(self) -> None:
        self._users: dict[str, dict] = {}

    def get(self, email: str) -> dict | None:
        return self._users.get(email)

    def put(self, email: str, record: dict) -> None:
        self._users[email] = record

    def count(self) -> int:
        return len(self._users)
