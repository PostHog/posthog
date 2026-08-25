"""Unit tests for the compose-override parity + the authed deep-health gate.

Self-contained: no network, no live box. Two seams are covered:

  - ``write_override`` must mirror hogland's scripts/posthog-preview-setup.sh —
    the PERSONHOG_ADDR web env plus the personhog-replica/router services. When
    those drifted, previews 500'd fleet-wide with "personhog client not
    configured" (2026-07-06 -> 07-10). The temporal pair is held to the same bar
    and fails even quieter: web schedules, nothing services the queue, and a
    materialization just never runs.
  - ``deep_health`` — after /_health, log into the seeded demo user and hit the
    endpoints that actually broke. Passes on 200s, raises with the failing
    step's body + a docker-logs tail on a 500, and is skipped on --no-seed.

Guarded on the SDK import (pulled per-run via ``uv run --with``), same as the
sibling tests.

    cd tools/hogbox-preview && python -m unittest discover tests
"""

from __future__ import annotations

import unittest

try:
    from hogbox_preview.backend import ExecResult
    from hogbox_preview.stack import PostHogPreviewStack

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False


class _RecordingBackend:
    """Duck-typed PreviewBackend. ``exec`` returns a scripted result keyed off
    the command so we can drive the probe down a pass or a fail path without a
    real box."""

    def __init__(self, *, probe_result: ExecResult | None = None):
        self.web_port = 8000
        self.files: dict[str, str] = {}
        self.execs: list[str] = []
        self.long_runs: list[str] = []
        self._probe_result = probe_result

    def write_file(self, remote_path, content) -> None:
        self.files[remote_path] = content if isinstance(content, str) else content.decode()

    def run_long(self, script, *, name, timeout: int = 1800, interval: int = 3) -> ExecResult:
        self.long_runs.append(script)
        return ExecResult(0, "", "")

    def exec(self, command, *, timeout: int = 120) -> ExecResult:
        self.execs.append(command)
        # The authed probe script is the one that logs in + hits /api endpoints.
        if "DEEP_HEALTH_OK" in command:
            return self._probe_result or ExecResult(0, "", "")
        # The failure path also greps docker logs; hand back a fake traceback.
        if "docker logs" in command:
            return ExecResult(
                0, "Traceback (most recent call last):\n  RuntimeError: personhog client not configured", ""
            )
        return ExecResult(0, "", "")


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class OverridePersonhogParityTest(unittest.TestCase):
    def _override(self, **kwargs) -> str:
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend, **kwargs)
        stack.write_override()
        return backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]

    def test_web_env_has_personhog_addr(self):
        self.assertIn("PERSONHOG_ADDR=personhog-router:50052", self._override())

    def test_personhog_services_defined(self):
        override = self._override()
        self.assertIn("personhog-replica:", override)
        self.assertIn("personhog-router:", override)
        # extends the shared base compose (HOBBY-style), not a standalone def.
        self.assertIn("file: docker-compose.base.yml", override)
        # replica points at the MAIN posthog DB (persons live there single-node).
        self.assertIn("PRIMARY_DATABASE_URL: postgres://posthog:posthog@db:5432/posthog", override)

    def test_image_tag_flows_into_personhog_images(self):
        # The personhog tag is the part of self.image after the last ':'.
        override = self._override(image="ghcr.io/posthog/posthog:abc123")
        self.assertIn("ghcr.io/posthog/posthog/personhog-replica:abc123", override)
        self.assertIn("ghcr.io/posthog/posthog/personhog-router:abc123", override)


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class OverrideTemporalParityTest(unittest.TestCase):
    """Same parity bar as personhog, for the services that run materializations."""

    def _override(self, **kwargs) -> str:
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend, **kwargs)
        stack.write_override()
        return backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]

    def test_temporal_services_overridden(self):
        override = self._override()
        self.assertIn("  temporal:", override)
        self.assertIn("  temporal-django-worker:", override)
        # ES off: base would otherwise drag an elasticsearch container into every
        # preview just to run workflows (postgres visibility is enough).
        self.assertIn("ENABLE_ES=false", override)

    def test_temporal_drops_the_inherited_elasticsearch_edge(self):
        # `extends` propagates depends_on and depends_on MERGES across files, so
        # ENABLE_ES=false alone still leaves temporal blocking on a ~1 GiB ES
        # container. Only `!override` drops the inherited edge.
        temporal_block = self._override().split("  temporal:", 1)[1].split("  temporal-django-worker:", 1)[0]
        self.assertIn("depends_on: !override", temporal_block)
        self.assertIn("db:", temporal_block)
        self.assertNotIn("elasticsearch", temporal_block)

    def test_temporal_mounts_the_dynamicconfig(self):
        # The auto-setup image doesn't ship the dynamicconfig file base points
        # DYNAMIC_CONFIG_FILE_PATH at; without the checkout's copy mounted the
        # server crash-loops and the container never turns healthy (cost a full
        # golden bake on 2026-08-07).
        temporal_block = self._override().split("  temporal:", 1)[1].split("  temporal-django-worker:", 1)[0]
        self.assertIn("- ./docker/temporal/dynamicconfig:/etc/temporal/config/dynamicconfig", temporal_block)

    def test_worker_serves_the_data_modeling_queue(self):
        # DEBUG=0 means the real queue names apply, and one worker serves exactly
        # one queue — materialized views schedule onto this one.
        self.assertIn("TEMPORAL_TASK_QUEUE=data-modeling-task-queue", self._override())

    def test_worker_shares_webs_secret_key(self):
        # TEMPORAL_SECRET_KEY defaults to SECRET_KEY and keys the payload codec;
        # a mismatch makes workflow payloads undecodable across the boundary.
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend)
        stack.write_override()
        override = backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]
        self.assertEqual(override.count(f"SECRET_KEY={stack.secret_key}"), 2)

    def test_worker_pins_the_image(self):
        # dev-full's worker carries `build: .` — an unpinned image turns
        # `up --no-build` into the 20-min build.
        self.assertIn(
            "    image: ghcr.io/posthog/posthog:abc123", self._override(image="ghcr.io/posthog/posthog:abc123")
        )

    def test_worker_mounts_the_prs_backend_source(self):
        # Without these the worker materializes views against stale :master.
        override = self._override()
        worker_block = override.split("  temporal-django-worker:", 1)[1]
        for src, dst in PostHogPreviewStack.MOUNTS:
            self.assertIn(f"- ./{src}:{dst}", worker_block)
        # ...but the frontend mounts stay web-only (the worker serves no HTTP).
        self.assertNotIn("/code/frontend/dist", worker_block)
        self.assertNotIn("/code/staticfiles", worker_block)

    def test_both_services_force_the_local_warehouse_path(self):
        # A preview runs DEBUG=0, so USE_LOCAL_SETUP has to be forced or every
        # warehouse path reaches for real AWS creds instead of the stack's MinIO.
        self.assertEqual(self._override().count("USE_LOCAL_SETUP=1"), 2)

    def test_temporal_server_started_with_deps_but_not_the_worker(self):
        # The server must be listening before web schedules; the worker imports
        # Django + touches the schema, so it can only start after migrate() —
        # up_web brings it up with the PR mounts instead.
        self.assertIn("temporal", PostHogPreviewStack.DEPS)
        self.assertNotIn("temporal-django-worker", PostHogPreviewStack.DEPS)

    def test_up_web_recreates_the_worker_too(self):
        # You can't add a bind mount to a running container, so the golden's warm
        # worker has to be recreated from the override or it keeps running
        # :master. Still --no-build (the override pins its image).
        backend = _RecordingBackend()
        PostHogPreviewStack(backend).up_web()
        script = backend.long_runs[-1]
        self.assertIn("up -d --no-build web temporal-django-worker", script)

    def test_migrate_registers_search_attributes_tolerantly(self):
        # Fresh temporal namespaces lack PostHogDagId & co. and /materialize/
        # 500s without them — migrate() must register them, but tolerantly: a
        # PR branch predating the management command must not abort bring-up.
        backend = _RecordingBackend()
        PostHogPreviewStack(backend).migrate()
        script = backend.long_runs[-1]
        self.assertIn("register_temporal_search_attributes", script)
        self.assertIn("WARN", script)  # non-fatal fallthrough, not a bare run

    def test_reset_database_recreates_temporal(self):
        # The wiped postgres volume held temporal's DBs, and only temporal's
        # auto-setup ENTRYPOINT recreates that schema — so a reset that leaves
        # the temporal container running strands it erroring forever.
        backend = _RecordingBackend()
        PostHogPreviewStack(backend).reset_database()
        script = backend.long_runs[-1]
        self.assertIn("rm -f db clickhouse web temporal temporal-django-worker", script)


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class DeepHealthTest(unittest.TestCase):
    def test_passes_when_probe_reports_ok(self):
        backend = _RecordingBackend(probe_result=ExecResult(0, "STEP projects 200\nDEEP_HEALTH_OK\n", ""))
        PostHogPreviewStack(backend).deep_health()
        # Ran the probe; didn't need to dump logs.
        self.assertTrue(any("DEEP_HEALTH_OK" in c for c in backend.execs))
        self.assertFalse(any("docker logs" in c for c in backend.execs))

    def test_probe_script_hits_the_endpoints_that_broke(self):
        backend = _RecordingBackend(probe_result=ExecResult(0, "DEEP_HEALTH_OK\n", ""))
        PostHogPreviewStack(backend).deep_health()
        script = next(c for c in backend.execs if "DEEP_HEALTH_OK" in c)
        self.assertIn("/login", script)
        self.assertIn("/api/login/", script)
        self.assertIn("/api/projects/@current/", script)
        self.assertIn("/api/environments/@current/query/", script)
        self.assertIn("HogQLQuery", script)
        self.assertIn("test@posthog.com", script)

    def test_raises_with_body_and_logs_on_500(self):
        # Probe fails at the projects step with a 500 + body.
        failing = ExecResult(
            0,
            "STEP login 200\nSTEP api_login 200\nSTEP projects 500\nBODY_START\npersonhog client not configured\nBODY_END\n",
            "",
        )
        backend = _RecordingBackend(probe_result=failing)
        with self.assertRaises(RuntimeError) as ctx:
            PostHogPreviewStack(backend).deep_health()
        msg = str(ctx.exception)
        # The failing step + body are surfaced...
        self.assertIn("STEP projects 500", msg)
        self.assertIn("personhog client not configured", msg)
        # ...and so is the web-log tail (the traceback that cost hours).
        self.assertIn("docker logs --tail 40 posthog-web-1", msg)
        self.assertIn("Traceback", msg)
        # It actually fetched the logs.
        self.assertTrue(any("docker logs" in c for c in backend.execs))

    def test_no_seed_still_probes_the_preseeded_golden(self):
        # The CI workflow calls `up --no-seed` (the golden is pre-seeded), so the
        # probe must RUN on no-seed runs — keying the gate off seed_demo_data
        # disabled it in exactly the production path (Codex review catch).
        backend = _RecordingBackend(probe_result=ExecResult(0, "DEEP_HEALTH_OK", ""))
        PostHogPreviewStack(backend, seed_demo_data=False).deep_health()
        self.assertTrue(any("DEEP_HEALTH_OK" in c for c in backend.execs))

    def test_no_seed_tolerates_failed_login_only(self):
        # A genuinely unseeded box has no demo user: a failed api_login on a
        # no-seed run soft-skips instead of raising...
        login_fail = ExecResult(1, "STEP login 200\nSTEP api_login 401\nBODY_START\n{}\nBODY_END", "")
        backend = _RecordingBackend(probe_result=login_fail)
        PostHogPreviewStack(backend, seed_demo_data=False).deep_health()  # no raise
        # ...but a post-login failure raises even on no-seed (app is unusable).
        later_fail = ExecResult(
            1, "STEP login 200\nSTEP api_login 200\nSTEP projects 500\nBODY_START\n{}\nBODY_END", ""
        )
        backend = _RecordingBackend(probe_result=later_fail)
        with self.assertRaises(RuntimeError):
            PostHogPreviewStack(backend, seed_demo_data=False).deep_health()

    def test_seeded_run_fails_hard_on_login_failure(self):
        login_fail = ExecResult(1, "STEP login 200\nSTEP api_login 401\nBODY_START\n{}\nBODY_END", "")
        backend = _RecordingBackend(probe_result=login_fail)
        with self.assertRaises(RuntimeError):
            PostHogPreviewStack(backend, seed_demo_data=True).deep_health()

    def test_personhog_services_started_with_deps(self):
        # Nothing else starts them (up_web brings up only web) — a cold/reset box
        # must not boot web pointing at a router that never started.
        self.assertIn("personhog-replica", PostHogPreviewStack.DEPS)
        self.assertIn("personhog-router", PostHogPreviewStack.DEPS)


if __name__ == "__main__":
    unittest.main()
