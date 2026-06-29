from products.merge_queue.backend.shadow import ShadowGuard


class _SpyGitHub:
    def __init__(self):
        self.merges: list = []
        self.statuses: list = []

    def merge(self, repo, number, sha):
        self.merges.append((repo, number, sha))

    def set_status(self, repo, sha, *, state, context, description):
        self.statuses.append((repo, sha, state))


class TestShadowGuard:
    def test_shadow_records_but_does_not_act(self):
        guard = ShadowGuard(github=None)
        assert guard.is_shadow is True
        # acts on nothing — no error, no side effect to observe
        guard.merge(repo="r", number=1, sha="s")
        guard.set_status(repo="r", sha="s", state="success", context="stampede")

    def test_live_guard_forwards_to_github(self):
        spy = _SpyGitHub()
        guard = ShadowGuard(github=spy)
        assert guard.is_shadow is False
        guard.merge(repo="r", number=1, sha="abc")
        guard.set_status(repo="r", sha="abc", state="success", context="stampede")
        assert spy.merges == [("r", 1, "abc")]
        assert spy.statuses == [("r", "abc", "success")]
