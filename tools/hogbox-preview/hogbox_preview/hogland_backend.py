"""Hogland preview layer, driven by the ``posthog-hogland`` SDK.

Restore a warmed golden snapshot into a hogbox (Firecracker microVM), run the
stack inside it, and reach its web over the box's own edge hostname. The box is
fronted by a **pen** — the stable named identity that outlives the box. Boxes
rotate IDs on every restore (a fresh golden restore per push); the pen, keyed on
a deterministic name (``preview-pr-1234``), persists and carries the
``current_box_id`` pointer plus repo/PR attribution. See ``docs/PENS.md`` in the
hogland repo.

Why the SDK and not the ``hogland`` CLI: the SDK is the whole PreviewBackend
surface, keyless, with one dependency (``uv run --with posthog-hogland``).
``client.create(snapshot_id=...)`` restores; ``box.exec`` / ``box.write_file``
run commands and write files over hogplane's HTTP API (no SSH); ``box.delete``
tears down; ``create_pen`` / ``update_pen`` track the stable identity. The CLI
route meant shipping a private-repo binary to the runner plus an SSH-key secret
for exec — neither is needed.

``create(web_port=...)`` opts the box into HTTP exposure, and ``box.web_url()``
returns its own per-box edge hostname (``https://<box>.<box-edge>/``, TLS
terminated at the edge, plain HTTP inside) — the clean URL posted to the PR.
``proxy_url`` (the authenticated path proxy) is only the fallback for a reused,
un-exposed ``--box-id`` box.
"""

from __future__ import annotations

import os
import re
import json
import time
import uuid
import shlex
import pathlib
import tempfile
import subprocess
import urllib.request
from urllib.parse import quote, urlsplit

from hogland import AccessType, AuthenticationError, BoxSpec, ConflictError, Hogland, NotFoundError, ServerError
from hogland._http import raise_for_status

from . import timing
from .backend import ExecResult, PreviewBackend

# hogplane caps a single write_file body at 64 MiB (octet-stream PUT). Blobs over
# that (the PR frontend dist tar) are shipped as sub-cap parts and `cat`'d back
# together in-box; _WRITE_CHUNK keeps headroom under the hard cap.
_WRITE_FILE_CAP = 64 * 1024 * 1024
_WRITE_CHUNK = 48 * 1024 * 1024

# Placement is best-effort server-side: a hogd node can die mid-restore (an OOM,
# a drain) and hogland surfaces it as a 5xx (e.g. `placement failed: ... EOF`).
# The next attempt lands on a healthy node, so retry create/restore on transient
# 5xx only — never on a 4xx, which is a real client error that a retry won't fix.
_CREATE_5XX_ATTEMPTS = 3
_CREATE_5XX_BACKOFF_SECONDS = (5, 15)  # slept BEFORE attempts 2 and 3

# A capacity 503 is NOT a "retry me" 5xx like the placement failures above: the
# server already burned ~4 minutes internally (auction retry budget, see
# hogplane's discovery.ErrNoCapacity / orchestrator.retryAuction) before giving
# up, so 3 client-side retries would tie up the CI runner for 12+ minutes and
# leave 3 failed boxes behind. The preview workflow's sticky comment already
# tells the user it'll retry on the next push, so fail fast here instead.
# Match on hogplane's stable error text (see discovery.ErrNoCapacity in the
# hogland repo) rather than only the 503 status, since other transient 5xx
# (placement EOF, etc.) also come back as 503-or-500 and must keep retrying.
_NO_CAPACITY_MESSAGE_SUBSTRING = "no hogd has capacity"


def _is_no_capacity_error(exc: ServerError) -> bool:
    """True if `exc` is hogland's "no capacity right now" 503, not some other
    transient 5xx. Defensive: any introspection failure here just falls back to
    the existing retry-every-5xx behaviour."""
    try:
        return _NO_CAPACITY_MESSAGE_SUBSTRING in str(exc)
    except Exception:
        return False


def _ephemeral_ssh_pubkey() -> str:
    """A throwaway ed25519 public key.

    ``access_type=ssh_public`` still requires *a* key at restore time, but
    exec/write_file go over the HTTP API, so this key never reaches the box.
    Keyless (``access_type=none``, shipped for service kinds like ``preview``)
    is the clean follow-up — switching drops this whole helper.
    """
    with tempfile.TemporaryDirectory() as d:
        key = pathlib.Path(d) / "id_ed25519"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-C", "hogbox-preview", "-f", str(key)],
            check=True,
        )
        return key.with_suffix(".pub").read_text().strip()


class HoglandBackend(PreviewBackend):
    def __init__(
        self,
        *,
        host: str | None = None,
        snapshot: str = "alias:posthog-preview-golden",
        cpus: float = 8,
        memory_mib: int = 16384,
        disk_gib: int = 100,
        disk_class: str = "mirrored",
        web_port: int = 8000,
        name: str = "posthog-preview",
        kind: str = "preview",
        ttl_seconds: int | None = None,
        box_id: str | None = None,
        token: str | None = None,
        timeout: float = 300.0,
        oidc_audience: str | None = None,
    ):
        super().__init__(web_port=web_port)
        # Hogland() reads HOG_TOKEN / HOG_HOST from env; --host/--token override.
        # A generous timeout is required: create() blocks server-side until the
        # restore completes (tens of seconds), which trips the SDK's short
        # default and raises httpx.ReadTimeout mid-restore.
        self._host = host
        self._timeout = timeout
        # In CI the bearer is a short-lived GitHub OIDC JWT; the bring-up outlives
        # it (restore alone eats minutes), so exec/write_file re-mint on 401.
        self._oidc_audience = oidc_audience or os.environ.get("HOG_OIDC_AUDIENCE")
        self._client = Hogland(token=token, base_url=host, timeout=timeout)
        self.snapshot = snapshot
        # The golden is pinned to this sizing; restore must MATCH it exactly
        # ("omit to inherit" is unreliable server-side).
        self.cpus = cpus
        self.memory_mib = memory_mib
        self.disk_gib = disk_gib
        self.disk_class = disk_class
        # `name` is the deterministic PEN name (e.g. preview-pr-123) — the stable
        # identity, conflict-free by design. The box name is NOT this: hogland
        # enforces per-owner name uniqueness across ALL box statuses (failed
        # included), and a failed placement holds its name for up to an hour, so a
        # deterministic box name makes a retry 409 against its own corpse. Each
        # created box gets `<name>-<6hex>` instead (see _create_kwargs), unique per
        # attempt. The pen persists across pushes; the box behind it rotates.
        self.name = name
        # kind="preview" gives the box hogland's 24h preview idle-TTL default
        # (sandbox is immortal — a leaked preview would never be reaped).
        self.kind = kind
        self.ttl_seconds = ttl_seconds
        self._box_id = box_id
        self._box = None  # hogland.Hogbox once provisioned
        self._pen = None  # shared.Pen once ensured (carries the stable id for web_url)

    # --- layer methods -------------------------------------------------------
    def provision(self) -> None:
        if self._box is not None:
            return
        if self._box_id:  # explicit reuse (debug / staged CI)
            timing.stage(f"attach to box {self._box_id}")
            self._box = self._client.get(self._box_id)
            self._wait_exec_ready()
            timing.stage("box exec ready")
            return
        # Stable identity first, then a fresh box from the golden. Each box gets a
        # per-attempt unique name so a failed placement cannot block a retry. The
        # pen outlives the box across pushes.
        timing.stage("pen resolve/create")
        self._ensure_pen()
        timing.stage("box restore start")
        self._box = self._restore_fresh()
        self._box_id = self._box.id
        # `running` means the VM resumed, not that hogpanion's HTTP API answers
        # yet — a restored box needs a beat before the first exec.
        self._wait_exec_ready()
        timing.stage("box restored (exec ready)")
        # Point the pen at the new box, re-send the spec so it carries the current
        # shape, and RE-ASSERT the hibernate/wake policies. The spec re-send heals
        # a pen left by an older SDK whose nested expose:{http_port} the server
        # dropped: such a pen has wake=on-request but no spec.web_port, and the
        # server rejects any update of it until the flat web_port is present.
        # Re-asserting on_idle/wake makes hibernation mandatory for every push:
        # with auto-previews the fleet is large, and always-on previews would be
        # unaffordable — so even a pen that somehow lost the policy (older create,
        # manual PATCH) is healed back to hibernate-on-idle here, not just at
        # create. Idempotent for a freshly-created pen.
        self._client.update_pen(
            self.name,
            current_box_id=self._box_id,
            spec=self._pen_spec(),
            on_idle="hibernate",
            wake="on-request",
        )

    def _box_name(self) -> str:
        # A per-attempt unique box name: `<pen-name>-<6hex>`. hogland's name
        # uniqueness spans failed boxes and a failed placement holds its name for
        # up to an hour, so reusing a name (deterministic, or even per-instance)
        # would make the 5xx retry 409 against its own corpse. Regenerate for
        # every create attempt so retries never self-conflict.
        return f"{self.name}-{uuid.uuid4().hex[:6]}"

    def _create_kwargs(self) -> dict:
        # The golden is pinned to this sizing; restore must MATCH it exactly.
        return {
            "snapshot_id": self.snapshot,
            "cpus": self.cpus,
            "memory_mib": self.memory_mib,
            "disk_gib": self.disk_gib,
            "disk_class": self.disk_class,
            "access_type": AccessType.ssh_public,
            "ssh_public_key": _ephemeral_ssh_pubkey(),
            "name": self._box_name(),
            "kind": self.kind,
            "ttl_seconds": self.ttl_seconds,
            # HTTP-expose the web port so the box gets its own box-front hostname
            # (https://<box>.<box-edge>/) — that's the URL we post to the PR.
            "web_port": self.web_port,
        }

    def _create(self):
        """Create/restore the box, retrying transient 5xx ServerErrors only.

        Placement can fail on a node death mid-restore (OOM / drain) and comes
        back as a 5xx; a retry seconds later lands on a healthy node. A 4xx is a
        real client error (bad spec) that a retry won't fix, so it propagates
        immediately. Each attempt draws a fresh unique box name via
        _create_kwargs, so a 5xx-failed attempt — which leaves a failed box
        holding its name for up to an hour — can't make the retry 409 against its
        own corpse.

        A "no capacity" 503 is the one 5xx that must NOT be retried here: the
        server already spent ~4 minutes on an auction retry budget before
        raising it, so retrying 3x would burn 12+ minutes of runner time and
        leave 3 failed boxes for one doomed run. Fail immediately with a clear
        message — the caller already tells the user this'll retry on the next
        push."""
        for attempt in range(_CREATE_5XX_ATTEMPTS):
            try:
                return self._client.create(**self._create_kwargs())
            except ServerError as exc:
                if _is_no_capacity_error(exc):
                    raise ServerError(
                        "hogland has no capacity right now; will retry on the next push",
                        status_code=exc.status_code,
                        body=exc.body,
                    ) from exc
                if attempt == _CREATE_5XX_ATTEMPTS - 1:
                    raise  # out of retries — surface the 5xx
                time.sleep(_CREATE_5XX_BACKOFF_SECONDS[attempt])
        # Unreachable: the loop either returns or raises on the last attempt.
        raise RuntimeError("unreachable")

    def _restore_fresh(self):
        """Restore the golden into a new box.

        Box names are per-attempt unique (`<pen-name>-<6hex>`), so a create can no
        longer 409 against a corpse left by a prior run or a prior 5xx attempt —
        which killed the old resolve-stale/delete/retry dance this used to need.
        Leftover corpses are swept in provision() after the pen is repointed."""
        return self._create()

    def attach(self) -> None:
        """Bind to the EXISTING preview box for this pen/name without restoring —
        the non-creating counterpart to provision(), used by the deferred
        swap-frontend path. Resolves the box bring_up already stood up (explicit
        --box-id, else the pen's current pointer, else a name lookup) and waits
        for its exec API, so exec/write_file/web_url act on the live box.
        """
        if self._box is not None:
            return
        # The bring-up may have burned most of the CI OIDC token's short life
        # before we get here, and the pen/box lookups below aren't wrapped in the
        # 401-retry that exec/write_file are — so mint a fresh token first
        # (best-effort no-op outside CI).
        self._refresh_auth()
        timing.stage("attach: resolve existing box")
        try:
            self._pen = self._client.get_pen(self.name)
        except NotFoundError:
            self._pen = None  # no pen (e.g. --box-id debug run) — web_url falls back to the box URL
        box = self._resolve_box()
        if box is None:
            raise RuntimeError(f"no live preview box found for {self.name!r} to swap the frontend into")
        self._box = box
        self._box_id = box.id
        self._wait_exec_ready()
        timing.stage("attach: box exec ready")

    def exec(self, command: str, *, timeout: int = 120) -> ExecResult:
        # The box exec API runs as root but doesn't set HOME; tools like git
        # (--global config) and docker expect it. Provide root's home.
        argv = ["bash", "-lc", command]
        try:
            r = self._require_box().exec(argv, timeout_seconds=timeout, env={"HOME": "/root"})
        except AuthenticationError:
            if not self._refresh_auth():
                raise
            r = self._require_box().exec(argv, timeout_seconds=timeout, env={"HOME": "/root"})
        return ExecResult(r.exit_code, r.stdout, r.stderr)

    def write_file(self, remote_path: str, content: bytes | str) -> None:
        data = content.encode() if isinstance(content, str) else content
        # The frontend dist tar blows past hogplane's 64 MiB per-PUT cap, so big
        # blobs go up as sub-cap parts and get reassembled in-box. Small writes
        # (every other caller) stay a single PUT.
        if len(data) > _WRITE_FILE_CAP:
            self._write_chunked(remote_path, data)
        else:
            self._put_file(remote_path, data)

    def _put_file(self, remote_path: str, data: bytes) -> None:
        # One PUT, re-minting the OIDC bearer once on a 401 — the bring-up
        # outlives a single short-lived CI token.
        try:
            self._require_box().write_file(remote_path, data, mkdir=True)
        except AuthenticationError:
            if not self._refresh_auth():
                raise
            self._require_box().write_file(remote_path, data, mkdir=True)

    def _write_chunked(self, remote_path: str, data: bytes) -> None:
        # Ship the blob as <=_WRITE_CHUNK parts, then `cat` them back in order
        # (listed explicitly, not globbed). The box is fresh each run, so there
        # are no stale parts to collide with.
        parts = []
        for i in range(0, len(data), _WRITE_CHUNK):
            part = f"{remote_path}.part{i // _WRITE_CHUNK:03d}"
            self._put_file(part, data[i : i + _WRITE_CHUNK])
            parts.append(part)
        quoted = " ".join(shlex.quote(p) for p in parts)
        r = self.exec(f"cat {quoted} > {shlex.quote(remote_path)} && rm -f {quoted}", timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"reassembling {remote_path} from {len(parts)} parts failed: {r.stderr.strip()}")

    @property
    def web_url(self) -> str:
        # The STABLE pen URL: https://<pen-id>.<edge>/. The pen outlives the box,
        # so this URL survives box recreation — hogland's box-http edge resolves
        # <pen-id> to the pen's current box (hogland #319). We derive the edge
        # base from the box's own per-box hostname (same edge, first label swapped
        # to the pen id) so there's no env-specific base to hardcode here.
        # Falls back to the box's own URL (no pen, or no gateway configured), then
        # to the authenticated path-proxy for an un-exposed reused box.
        box = self._require_box()
        box_url = box.web_url()
        if box_url and self._pen is not None and self._pen.id:
            host = urlsplit(box_url).hostname or ""
            base = host.split(".", 1)[1] if "." in host else ""
            if base:
                return f"https://{self._pen.id}.{base}"
        if box_url:
            return box_url.rstrip("/")
        return box.proxy_url(self.web_port).rstrip("/")

    @property
    def box_id(self) -> str | None:
        return self._box_id

    @property
    def pen_id(self) -> str | None:
        # The pen's stable id (e.g. pen-aa47b706211f) once the pen is ensured.
        # Used to build the hogland admin/console link for the preview. Mirrors
        # web_url's guard so an ensured-but-idless pen returns None, never "".
        return self._pen.id if (self._pen is not None and self._pen.id) else None

    def destroy(self) -> None:
        # An explicit box id is owned by this invocation. When its pen was
        # already removed, still release that requested box rather than leaving
        # it until its TTL.
        if self._box_id:
            try:
                self._delete_pen_if_current_box(self._box_id)
                return
            except ConflictError:
                self._delete_explicit_box()
                return
            except NotFoundError:
                self._delete_explicit_box()
                return

        # Name-only cleanup is an authoritative teardown for a closed or
        # opted-out preview, so it intentionally removes the pen's current box.
        try:
            pen = self._client.get_pen(self.name)
        except NotFoundError:
            return
        if not pen.current_box_id:
            try:
                self._delete_pen()
            except NotFoundError:
                pass
            except Exception as e:
                timing.stage(f"warn: couldn't delete empty pen during teardown: {e}")
            return
        try:
            self._delete_pen_if_current_box(pen.current_box_id)
        except ConflictError:
            timing.stage("teardown skipped: preview was replaced by a newer run")
        except NotFoundError:
            pass

    def _delete_pen_if_current_box(self, expected_box_id: str) -> None:
        # The workflow currently installs an SDK version that predates the
        # public expected_current_box_id argument. Keep the request explicit so
        # the safety fence works before that dependency is bumped.
        response = self._client._http.delete(
            f"/v1/pens/{quote(self.name, safe='')}",
            params={"expected_current_box_id": expected_box_id},
        )
        raise_for_status(response)

    def _delete_pen(self) -> None:
        response = self._client._http.delete(f"/v1/pens/{quote(self.name, safe='')}")
        raise_for_status(response)

    def _delete_explicit_box(self) -> None:
        try:
            self._client.get(self._box_id).delete()
        except NotFoundError:
            pass
        except Exception as e:
            timing.stage(f"warn: couldn't delete explicit box during teardown: {e}")

    # --- pen: the stable identity over the box lifecycle ---------------------
    def _ensure_pen(self) -> None:
        """Get-or-create the pen. Keyed on the deterministic name, it persists
        across pushes while the box rotates, carrying the ``current_box_id``
        pointer + attribution. Idempotent and race-safe: a concurrent CI re-run
        that wins the create is simply found on the retry.

        ``on_idle=hibernate`` / ``wake=on-request`` are now enforced server-side:
        hogland's idle-TTL reaper snapshots-and-sleeps an idle preview to S3
        (zero node cost), and the box-front edge wakes it on the next request
        behind a "waking up" interstitial. ``wake`` requires an exposed spec,
        which ``_pen_spec`` provides; the idle window is the pen's
        ``ttl_seconds``."""
        try:
            self._pen = self._client.get_pen(self.name)
            return
        except NotFoundError:
            pass
        try:
            self._pen = self._client.create_pen(
                self.name,
                source_alias=self._source_alias(),
                spec=self._pen_spec(),
                on_idle="hibernate",
                wake="on-request",
                metadata=self._pen_metadata(),
            )
        except ConflictError:
            # A racing run created it between our get and create — fetch the winner.
            self._pen = self._client.get_pen(self.name)

    def _pen_spec(self) -> BoxSpec:
        """The spec the pen remembers — sizing, the golden it seeds from, and the
        exposed web port (``web_port``, which is what makes ``wake=on-request`` a
        valid policy). Records enough for a wake/EnsureUp to rebuild the box from
        the pen alone. Built as the SDK's BoxSpec so the wire body carries every
        field the server requires (the throughput caps default to 0) — this code
        never re-derives the contract by hand."""
        return BoxSpec(
            snapshot_id=self.snapshot,
            cpus=self.cpus,
            memory_mib=self.memory_mib,
            disk_gib=self.disk_gib,
            disk_class=self.disk_class,
            kind=self.kind,
            web_port=self.web_port,
            ttl_seconds=self.ttl_seconds,
        )

    def _source_alias(self) -> str | None:
        """The seed alias the pen can re-restore from if its snapshots are GC'd.
        ``snapshot`` carries the ``alias:`` resolve hint; the pen stores the bare
        name (None when a concrete snap id was passed)."""
        prefix = "alias:"
        return self.snapshot[len(prefix) :] if self.snapshot.startswith(prefix) else None

    def _pen_metadata(self) -> dict[str, str] | None:
        """Display-only attribution (repo / PR / author / backlink) read from the
        GitHub Actions env, best-effort — it's the "who is this preview for" shown
        in pen listings, never used in a server decision. Empty on local runs ->
        omit the field."""
        env = os.environ
        repo = env.get("GITHUB_REPOSITORY")
        actor = env.get("GITHUB_ACTOR")
        server = env.get("GITHUB_SERVER_URL", "https://github.com")
        pr = env.get("PR") or env.get("PR_NUMBER")
        if not pr and self.name.startswith("preview-pr-"):
            pr = self.name[len("preview-pr-") :]
        md: dict[str, str] = {}
        if repo:
            md["repo"] = repo
        if pr:
            md["pr"] = pr
        if actor:
            md["author"] = actor
        if repo and pr:
            md["url"] = f"{server}/{repo}/pull/{pr}"
        return md or None

    # --- CI token refresh ----------------------------------------------------
    def _mint_oidc(self) -> str | None:
        """Mint a fresh GitHub Actions OIDC token, or None when not in CI.

        GitHub issues short-lived JWTs and the bring-up outlives one (the restore
        alone eats minutes before the first stack step), so exec/write_file
        re-mint on 401. The request URL + token are valid for the whole job, so
        this can be called as often as needed. The audience must match the
        deploy's github_oidc TrustMapping (HOG_OIDC_AUDIENCE)."""
        url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
        rtok = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        if not (url and rtok and self._oidc_audience):
            return None
        req = urllib.request.Request(
            f"{url}&audience={self._oidc_audience}",
            headers={"Authorization": f"bearer {rtok}"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 — fixed GitHub host  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            return json.load(r).get("value")

    def _refresh_auth(self) -> bool:
        """Swap in a fresh OIDC token after a 401. Returns False outside CI
        (nothing to re-mint — let the original AuthenticationError propagate)."""
        fresh = self._mint_oidc()
        if not fresh:
            return False
        self._client = Hogland(token=fresh, base_url=self._host, timeout=self._timeout)
        if self._box is not None:
            self._box = self._client.get(self._box_id)
        return True

    # --- internal ------------------------------------------------------------
    def _require_box(self):
        if self._box is None:
            raise RuntimeError("provision() must run before the box is usable")
        return self._box

    def _name_matches(self, box_name: str | None) -> bool:
        # A box belongs to this preview if its name is exactly the pen name
        # (a legacy box from before per-box names) or the pen name plus exactly
        # the 6-hex attempt tag _box_name() mints. Anchoring on the full suffix
        # shape (not a bare prefix) keeps pen names that nest — "foo" vs
        # "foo-bar" — from cross-matching each other's boxes.
        if not box_name:
            return False
        if box_name == self.name:
            return True
        return re.fullmatch(re.escape(self.name) + r"-[0-9a-f]{6}", box_name) is not None

    def _resolve_box(self):
        """Find the box to act on: the live handle, an explicit id, the pen's
        current pointer, or — last resort — a name scan over live boxes matching
        this preview's name (exact or `<name>-` prefix), preferring a running box.
        Used by attach() (swap-frontend) and destroy() when the pen pointer is
        missing or dangling."""
        if self._box is not None:
            return self._box
        if self._box_id:
            return self._client.get(self._box_id)
        if self.name:
            try:
                # Reuse an already-loaded pen (attach() fetches it just before
                # calling here) instead of a second GET for the same name.
                pen = self._pen if self._pen is not None else self._client.get_pen(self.name)
                if pen.current_box_id:
                    return self._client.get(pen.current_box_id)
            except NotFoundError:
                pass  # no pen, or its box was already reaped — fall through
            # iter_boxes returns newest-first; take the first name match, but
            # prefer a running one over a corpse if the list view carries status.
            fallback_id = None
            for v in self._client.iter_boxes():
                if not self._name_matches(getattr(v.spec, "name", None)):
                    continue
                if getattr(v, "status", None) == "running":
                    return self._client.get(v.id)
                if fallback_id is None:
                    fallback_id = v.id
            if fallback_id is not None:
                return self._client.get(fallback_id)
        return None

    def _wait_exec_ready(self, *, timeout: int = 300, interval: int = 5) -> None:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            try:
                r = self._box.exec(["true"], timeout_seconds=20)
                if r.exit_code == 0:
                    return
                last = r.stderr or ""
            except AuthenticationError as e:
                # A multi-minute restore can outlive the CI OIDC bearer, and this
                # poll runs before the first exec()/write_file() that would refresh
                # it — so re-mint here too, or readiness spins to timeout on a
                # token that expired mid-restore. _refresh_auth swaps self._box to
                # the fresh client's handle. Guard it: a transient failure while
                # re-minting (token endpoint / get() blip) must be polled through,
                # not raised out of the loop.
                last = str(e)
                try:
                    self._refresh_auth()
                except Exception as refresh_err:  # noqa: BLE001 — keep polling
                    last = f"{e}; refresh failed: {refresh_err}"
            except Exception as e:  # noqa: BLE001 — keep polling through transient API errors
                last = str(e)
            time.sleep(interval)
        raise RuntimeError(f"box {self._box_id} exec API not ready within {timeout}s (last: {last})")
