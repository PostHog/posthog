from __future__ import annotations

import json

import unittest
from unittest.mock import MagicMock, patch

from hogbox_preview.desktop_profile import build_deployment_metadata_document, build_desktop_readiness_script


class DesktopReadiness(unittest.TestCase):
    def test_oauth_readiness_requires_matching_metadata_token_and_access(self) -> None:
        metadata = json.loads(
            build_deployment_metadata_document(pr_number=123, commit_sha="1" * 40, deployment_generation=1)
        )
        for failure in (None, "revision", "authorization", "access"):
            with self.subTest(failure=failure):
                bodies = [
                    {**metadata, "commitSha": "2" * 40} if failure == "revision" else metadata,
                    "login page",
                    {},
                    {"id": 7},
                    {
                        "redirect_to": "posthog-code-preview-pr-123://callback?"
                        + ("error=invalid_scope" if failure == "authorization" else "code=grant")
                    },
                    {"access_token": "fake-preview-token"},
                    {"id": 9},
                    {"allowed": failure != "access"},
                ]
                opener = MagicMock()
                responses = []
                for body in bodies:
                    response = MagicMock()
                    response.__enter__.return_value = response
                    response.status = 200
                    response.read.return_value = json.dumps(body).encode()
                    responses.append(response)
                opener.open.side_effect = responses
                with patch("urllib.request.build_opener", return_value=opener), patch("builtins.print") as output:
                    script = build_desktop_readiness_script(pr_number=123, web_port=8000, commit_sha="1" * 40)
                    if failure:
                        with self.assertRaises(RuntimeError):
                            exec(compile(script, "readiness", "exec"), {})
                        output.assert_not_called()
                    else:
                        exec(compile(script, "readiness", "exec"), {})
                        output.assert_called_once_with("DESKTOP_READY_OK")
                        requests = [call.args[0] for call in opener.open.call_args_list]
                        authorization = json.loads(requests[4].data)
                        self.assertEqual(authorization["code_challenge_method"], "S256")
                        self.assertEqual(authorization["scoped_teams"], [7])
                        self.assertIn(b"code_verifier=", requests[5].data)
                        self.assertEqual(requests[-1].get_header("Authorization"), "Bearer fake-preview-token")
                        self.assertTrue(requests[-1].full_url.endswith("/api/projects/7/desktop/access/"))
                        self.assertTrue(all(call.kwargs["timeout"] == 15 for call in opener.open.call_args_list))


if __name__ == "__main__":
    unittest.main()
