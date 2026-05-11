from posthog.test.base import APIBaseTest

from unittest.mock import AsyncMock, MagicMock, patch

from products.replay_vision.backend.models.replay_lens import LensModel, LensType, ReplayLens


class TestObserveAction(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_patcher = patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_patcher.start()
        self.lens = ReplayLens.objects.create(
            team=self.team,
            name="my-lens",
            lens_type=LensType.MONITOR,
            lens_config={"prompt": "did the user check out?"},
            model=LensModel.GEMINI_3_FLASH,
        )

    def tearDown(self) -> None:
        self.flag_patcher.stop()
        super().tearDown()

    @property
    def observe_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/lenses/{self.lens.id}/observe/"

    def _patch_temporal(self, workflow_id: str = "wf-test") -> tuple[MagicMock, AsyncMock]:
        mock_handle = MagicMock(id=workflow_id)
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock(return_value=mock_handle)
        connect_mock = AsyncMock(return_value=mock_client)
        patcher = patch("products.replay_vision.backend.api.lenses.async_connect", connect_mock)
        return patcher, connect_mock

    def test_observe_returns_202_with_workflow_id(self) -> None:
        patcher, connect_mock = self._patch_temporal("wf-123")
        with patcher:
            resp = self.client.post(self.observe_url, data={"session_id": "sess-1"}, format="json")
        self.assertEqual(resp.status_code, 202, resp.json())
        body = resp.json()
        self.assertEqual(body["session_id"], "sess-1")
        self.assertEqual(body["lens_id"], str(self.lens.id))
        self.assertEqual(body["workflow_id"], "wf-123")
        connect_mock.assert_awaited_once()

    def test_observe_rejects_missing_session_id(self) -> None:
        patcher, _ = self._patch_temporal()
        with patcher:
            resp = self.client.post(self.observe_url, data={}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_observe_rejects_blank_session_id(self) -> None:
        patcher, _ = self._patch_temporal()
        with patcher:
            resp = self.client.post(self.observe_url, data={"session_id": "   "}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_observe_404_on_unknown_lens(self) -> None:
        patcher, _ = self._patch_temporal()
        with patcher:
            resp = self.client.post(
                f"/api/environments/{self.team.id}/vision/lenses/00000000-0000-0000-0000-000000000000/observe/",
                data={"session_id": "sess-1"},
                format="json",
            )
        self.assertEqual(resp.status_code, 404)
