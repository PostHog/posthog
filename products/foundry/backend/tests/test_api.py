from posthog.test.base import APIBaseTest

from rest_framework import status


class TestBetEndpoints(APIBaseTest):
    def _create(self) -> dict:
        response = self.client.post(
            f"/api/projects/{self.team.id}/bets/",
            data={
                "slug": "checkout-friction",
                "hypothesis": "Reducing checkout steps from 3 to 1 raises purchase conversion",
                "success_metric": {"name": "purchase conversion rate", "target": "+10%"},
                "guardrails": [{"name": "error rate", "constraint": "must not rise"}],
                "budget": {"usd": 50, "time_hours": 24, "iterations": 3},
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def test_lifecycle_over_http(self):
        bet = self._create()
        assert bet["state"] == "drafted"
        assert bet["execution_mode"] == "external"
        bet_url = f"/api/projects/{self.team.id}/bets/{bet['id']}"

        funded = self.client.post(f"{bet_url}/fund/")
        assert funded.status_code == status.HTTP_200_OK, funded.json()
        assert funded.json()["state"] == "funded"
        assert funded.json()["feature_flag_key"] == "bet-checkout-friction"

        # funding twice is an invalid transition
        assert self.client.post(f"{bet_url}/fund/").status_code == status.HTTP_400_BAD_REQUEST

        for kind, payload, expected_state in [
            ("run.started", {}, "building"),
            ("gate.result", {"pass": False, "violations": [{"code": "tests"}]}, "building"),
            ("gate.result", {"pass": True, "violations": []}, "gated"),
            ("exposure.started", {}, "exposed"),
        ]:
            event = self.client.post(f"{bet_url}/events/", data={"kind": kind, "payload": payload}, format="json")
            assert event.status_code == status.HTTP_201_CREATED, event.json()
            assert self.client.get(bet_url).json()["state"] == expected_state

        # the reserved system kind is not accepted from writers
        rejected = self.client.post(f"{bet_url}/events/", data={"kind": "state.changed"}, format="json")
        assert rejected.status_code == status.HTTP_400_BAD_REQUEST

        verdict = self.client.post(f"{bet_url}/verdict/", data={"verdict": "promoted"}, format="json")
        assert verdict.status_code == status.HTTP_200_OK, verdict.json()
        assert verdict.json()["state"] == "archived"
        assert verdict.json()["verdict"] == "promoted"

        events = self.client.get(f"{bet_url}/events/").json()
        assert [e["kind"] for e in events if e["kind"] != "state.changed"] == [
            "run.started",
            "gate.result",
            "gate.result",
            "exposure.started",
        ]

        listed = self.client.get(f"/api/projects/{self.team.id}/bets/").json()
        assert [b["id"] for b in listed] == [bet["id"]]

    def test_node_events_wire_up_the_node_tree_endpoint(self):
        bet = self._create()
        bet_url = f"/api/projects/{self.team.id}/bets/{bet['id']}"
        self.client.post(f"{bet_url}/fund/")

        malformed = self.client.post(f"{bet_url}/events/", data={"kind": "node.spawned", "payload": {}}, format="json")
        assert malformed.status_code == status.HTTP_400_BAD_REQUEST

        spawned = self.client.post(
            f"{bet_url}/events/",
            data={"kind": "node.spawned", "payload": {"node_id": "root", "runner": "claude-code"}},
            format="json",
        )
        assert spawned.status_code == status.HTTP_201_CREATED, spawned.json()

        nodes = self.client.get(f"{bet_url}/nodes/").json()
        assert [n["node_id"] for n in nodes] == ["root"]
        assert nodes[0]["status"] == "spawned"
