"""Build and validate bounded credential-free Git publication artifacts."""

from __future__ import annotations

import os
import re
import sys
import json
import shutil
import hashlib
import resource
import tempfile
import subprocess
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from textwrap import dedent

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.publication_transport import NormalizedTreeOperation

_SAFE_MODES = {"100644", "100755"}
_SENSITIVE_TEXT = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})")
_GENERATED_PARTS = frozenset({"node_modules", "__pycache__", "dist", "build", ".next", ".git"})
_ARTIFACT_OBJECT_COUNT = 3


class PublicationBundleError(ValueError):
    pass


@frozen
class PublicationBundleLimits:
    max_bundle_bytes: int = 10 * 1024 * 1024
    max_blob_bytes: int = 512 * 1024
    max_total_bytes: int = 2 * 1024 * 1024
    max_changed_files: int = 200
    max_path_bytes: int = 240
    command_timeout_seconds: int = 15


@frozen
class PublicationBundlePlan:
    workspace_path: Path
    export_root: Path
    repository: str
    base_commit: str
    commit_message: str
    commit_timestamp: int
    limits: PublicationBundleLimits = PublicationBundleLimits()

    def __post_init__(self) -> None:
        if not self.workspace_path.is_absolute() or not self.export_root.is_absolute():
            raise PublicationBundleError("Publication paths must be absolute")
        if not re.fullmatch(r"[0-9a-f]{40}", self.base_commit):
            raise PublicationBundleError("Publication base must be a full lowercase SHA")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise PublicationBundleError("Publication repository is invalid")
        if not self.commit_message or len(self.commit_message.encode()) > 500:
            raise PublicationBundleError("Publication commit message is invalid")
        if not 0 < self.commit_timestamp < 2**31:
            raise PublicationBundleError("Publication timestamp is invalid")
        if any(
            value <= 0
            for value in (
                self.limits.max_bundle_bytes,
                self.limits.max_blob_bytes,
                self.limits.max_total_bytes,
                self.limits.max_changed_files,
                self.limits.max_path_bytes,
                self.limits.command_timeout_seconds,
            )
        ):
            raise PublicationBundleError("Publication limits must be positive")


@frozen
class PublicationBundle:
    bundle_path: Path
    artifact_head_sha: str
    byte_count: int
    export_directory: Path


@frozen
class ValidatedPublicationBundle:
    artifact_head_sha: str
    base_tree_sha: str
    head_tree_sha: str
    operations: tuple[NormalizedTreeOperation, ...]


def validate_bundle_path_and_text(*, path: str, text: str) -> None:
    candidate = PurePosixPath(path)
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or any(part in _GENERATED_PARTS for part in candidate.parts)
    ):
        raise PublicationBundleError("Publication bundle path is unsafe")
    if _SENSITIVE_TEXT.search(text):
        raise PublicationBundleError("Publication bundle contains sensitive text")


def _safe_git_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_CONFIG_COUNT": "4",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_CONFIG_KEY_1": "core.hooksPath",
        "GIT_CONFIG_VALUE_1": os.devnull,
        "GIT_CONFIG_KEY_2": "core.attributesFile",
        "GIT_CONFIG_VALUE_2": os.devnull,
        "GIT_CONFIG_KEY_3": "commit.gpgSign",
        "GIT_CONFIG_VALUE_3": "false",
    }


def _resource_limiter(limits: PublicationBundleLimits) -> Callable[[], None]:
    def apply_limits() -> None:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for kind, requested in (
            (resource.RLIMIT_CPU, limits.command_timeout_seconds),
            (resource.RLIMIT_FSIZE, limits.max_bundle_bytes + 2 * 1024 * 1024),
            (resource.RLIMIT_NOFILE, 64),
        ):
            _soft, hard = resource.getrlimit(kind)
            bounded = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
            resource.setrlimit(kind, (bounded, bounded))

    return apply_limits


def _run_git(args: list[str], *, cwd: Path, limits: PublicationBundleLimits, input_bytes: bytes | None = None) -> bytes:
    try:
        return subprocess.run(
            ["/usr/bin/git", "--no-optional-locks", "-c", "diff.external=", "-c", "core.pager=cat", *args],
            cwd=cwd,
            env=_safe_git_environment(),
            input=input_bytes,
            capture_output=True,
            check=True,
            timeout=limits.command_timeout_seconds,
            preexec_fn=_resource_limiter(limits),
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
        raise PublicationBundleError("Safe Git command failed") from err


def _validate_pack_header(payload: bytes) -> None:
    offset = payload.find(b"\n\nPACK")
    if offset < 0:
        raise PublicationBundleError("Publication bundle has no pack")
    pack = payload[offset + 2 :]
    if len(pack) < 12 or pack[:4] != b"PACK":
        raise PublicationBundleError("Publication bundle pack is malformed")
    if int.from_bytes(pack[4:8], "big") not in {2, 3} or int.from_bytes(pack[8:12], "big") != _ARTIFACT_OBJECT_COUNT:
        raise PublicationBundleError("Publication bundle has a noncanonical object count")


def _manifest(repository: Path, head: str, plan: PublicationBundlePlan) -> dict[str, object]:
    tree = _run_git(["ls-tree", "-r", "-z", head], cwd=repository, limits=plan.limits).rstrip(b"\0").split(b"\0")
    if len(tree) != 1 or not tree[0].startswith(b"100644 blob ") or not tree[0].endswith(b"\tmanifest.json"):
        raise PublicationBundleError("Publication artifact tree is invalid")
    object_id = tree[0].split(b" ", 2)[2].split(b"\t", 1)[0].decode()
    size = _run_git(["cat-file", "-s", object_id], cwd=repository, limits=plan.limits).strip()
    if not size.isdigit() or int(size) > plan.limits.max_total_bytes + 128_000:
        raise PublicationBundleError("Publication manifest is oversized")
    try:
        value = json.loads(_run_git(["cat-file", "blob", object_id], cwd=repository, limits=plan.limits))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise PublicationBundleError("Publication manifest is malformed") from err
    if not isinstance(value, dict):
        raise PublicationBundleError("Publication manifest is malformed")
    return value


def build_publication_bundle_script(plan: PublicationBundlePlan) -> str:
    payload = json.dumps(
        {
            "workspace": str(plan.workspace_path),
            "export_root": str(plan.export_root),
            "repository": plan.repository,
            "base": plan.base_commit,
            "message": plan.commit_message,
            "timestamp": plan.commit_timestamp,
            "limits": {
                "bundle": plan.limits.max_bundle_bytes,
                "blob": plan.limits.max_blob_bytes,
                "total": plan.limits.max_total_bytes,
                "files": plan.limits.max_changed_files,
                "path": plan.limits.max_path_bytes,
                "timeout": plan.limits.command_timeout_seconds,
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return dedent(
        f"""\
        import os,re,json,stat,tempfile,subprocess,hashlib
        from pathlib import Path
        P=json.loads({payload!r}); L=P["limits"]
        E={{"PATH":"/usr/bin:/bin","HOME":"/nonexistent","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null","GIT_ATTR_NOSYSTEM":"1","GIT_TERMINAL_PROMPT":"0","GIT_ALLOW_PROTOCOL":"","GIT_CONFIG_COUNT":"4","GIT_CONFIG_KEY_0":"core.fsmonitor","GIT_CONFIG_VALUE_0":"false","GIT_CONFIG_KEY_1":"core.hooksPath","GIT_CONFIG_VALUE_1":"/dev/null","GIT_CONFIG_KEY_2":"core.attributesFile","GIT_CONFIG_VALUE_2":"/dev/null","GIT_CONFIG_KEY_3":"commit.gpgSign","GIT_CONFIG_VALUE_3":"false"}}
        secret=re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{{20,}}|github_pat_[A-Za-z0-9_]{{20,}}|AKIA[0-9A-Z]{{16}})")
        generated={{"node_modules","__pycache__","dist","build",".next",".git"}}
        def bad(message): raise RuntimeError(message)
        def git(args,cwd,data=None,extra=None):
            env=dict(E); env.update(extra or {{}})
            try: return subprocess.run(["/usr/bin/git","--no-optional-locks","-c","diff.external=","-c","core.pager=cat",*args],cwd=cwd,env=env,input=data,capture_output=True,check=True,timeout=L["timeout"]).stdout
            except Exception as error: raise RuntimeError("safe Git command failed") from error
        def path_ok(value):
            try: encoded=value.encode("utf-8","strict")
            except UnicodeError: bad("non-UTF-8 path")
            parts=value.split("/")
            if not value or value.startswith("/") or "\\\\" in value or "\\x00" in value or any(x in {{"",".",".."}} for x in parts) or any(x in generated for x in parts) or len(encoded)>L["path"]: bad("unsafe path")
        def read_file(root,rel):
            descriptor=os.open(root,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0))
            try:
                parts=rel.split("/")
                for part in parts[:-1]:
                    next_descriptor=os.open(part,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0),dir_fd=descriptor)
                    os.close(descriptor); descriptor=next_descriptor
                file_descriptor=os.open(parts[-1],os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=descriptor)
                try:
                    details=os.fstat(file_descriptor)
                    if not stat.S_ISREG(details.st_mode) or details.st_nlink!=1 or details.st_size>L["blob"]: bad("unsafe changed file")
                    chunks=[]; remaining=details.st_size
                    while remaining:
                        chunk=os.read(file_descriptor,min(65536,remaining))
                        if not chunk: bad("changed file truncated during read")
                        chunks.append(chunk); remaining-=len(chunk)
                    if os.read(file_descriptor,1) or os.fstat(file_descriptor).st_size!=details.st_size: bad("changed file changed during read")
                    return b"".join(chunks),details.st_mode
                finally: os.close(file_descriptor)
            finally: os.close(descriptor)
        workspace=Path(P["workspace"]).resolve(strict=True); root=Path(P["export_root"]).resolve(strict=True); gd=workspace/".git"
        if not gd.is_dir() or gd.is_symlink() or root.is_symlink(): bad("unsafe workspace")
        cfg=(gd/"config")
        if cfg.is_symlink() or not cfg.is_file() or cfg.stat().st_size>65536: bad("unsafe Git config")
        section=None; allowed={{"core":{{"repositoryformatversion","filemode","bare","logallrefupdates","symlinks","ignorecase","precomposeunicode"}},"extensions":{{"objectformat"}},"remote":{{"url","fetch"}},"branch":{{"remote","merge"}}}}
        for line in cfg.read_text().splitlines():
            line=line.strip()
            if not line or line.startswith(("#",";")): continue
            header=re.fullmatch(r'\\[([A-Za-z]+)(?: "([^"]+)")?\\]',line)
            if header:
                section=header.group(1).lower(); name=header.group(2)
                remote_ok=section=="remote" and re.fullmatch(r"[A-Za-z0-9_.-]{{1,100}}",name or "")
                branch_ok=section=="branch" and re.fullmatch(r"[A-Za-z0-9._/-]{{1,255}}",name or "") and not name.startswith("/") and not name.endswith("/") and ".." not in name and "//" not in name
                if section not in allowed or (section in {{"remote","branch"}} and not (remote_ok or branch_ok)) or (section not in {{"remote","branch"}} and name is not None): bad("unsafe Git config")
            elif section is None or "=" not in line or line.split("=",1)[0].strip().lower() not in allowed[section]: bad("unsafe Git config")
        for dangerous in (gd/"objects"/"info"/"alternates",gd/"info"/"grafts",gd/"modules",workspace/".gitmodules",gd/"refs"/"replace"):
            if dangerous.exists() or dangerous.is_symlink(): bad("unsafe Git topology")
        if git(["rev-list","--parents","-n","1",P["base"]],workspace).split()[0].decode()!=P["base"]: bad("missing protected base")
        changed=set(filter(None,(git(["diff","--name-only","-z","--no-renames","--no-ext-diff","--no-textconv",P["base"],"--"],workspace)+git(["ls-files","--others","-z"],workspace)).decode("utf-8","strict").split("\\0")))
        if not changed or len(changed)>L["files"]: bad("invalid changed file count")
        operations=[]; total=0; index=Path(tempfile.mkstemp(prefix="publication-index-")[1]); index.unlink()
        extra={{"GIT_INDEX_FILE":str(index)}}; git(["read-tree",P["base"]],workspace,extra=extra)
        try:
            for rel in sorted(changed):
                path_ok(rel)
                staged=git(["ls-files","-s","--",rel],workspace).split()
                if staged and staged[0]==b"160000": bad("submodules are forbidden")
                try: content,details_mode=read_file(workspace,rel)
                except FileNotFoundError:
                    git(["update-index","--force-remove","--",rel],workspace,extra=extra); operations.append({{"path":rel,"status":"delete","mode":"100644"}}); continue
                except OSError: bad("unsafe changed file")
                total+=len(content)
                if total>L["total"] or b"\\0" in content: bad("unsafe changed file")
                try: text=content.decode("utf-8","strict")
                except UnicodeDecodeError: bad("binary changed file")
                if secret.search(text): bad("sensitive changed file")
                mode="100755" if details_mode & stat.S_IXUSR else "100644"
                oid=git(["hash-object","-w","--no-filters","--stdin"],workspace,data=content).decode().strip()
                git(["update-index","--add","--cacheinfo",mode+","+oid+","+rel],workspace,extra=extra)
                operations.append({{"path":rel,"status":"upsert","mode":mode,"object_id":oid,"text":text}})
            base_tree=git(["rev-parse",P["base"]+"^{{tree}}"],workspace).decode().strip(); head_tree=git(["write-tree"],workspace,extra=extra).decode().strip()
        finally:
            try: index.unlink()
            except FileNotFoundError: pass
        manifest={{"version":1,"repository":P["repository"],"base_commit":P["base"],"base_tree":base_tree,"head_tree":head_tree,"commit_message":P["message"],"commit_timestamp":P["timestamp"],"operations":operations}}
        export=Path(tempfile.mkdtemp(prefix="publication-",dir=root)); os.chmod(export,0o700); repo=export/"artifact.git"; git(["init","--bare",str(repo)],export)
        body=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode(); oid=git(["hash-object","-w","--stdin"],repo,data=body).decode().strip()
        artifact_index=export/"artifact.index"; artifact_env={{"GIT_INDEX_FILE":str(artifact_index)}}; git(["update-index","--add","--cacheinfo","100644,"+oid+",manifest.json"],repo,extra=artifact_env); tree=git(["write-tree"],repo,extra=artifact_env).decode().strip()
        stamp=str(P["timestamp"])+" +0000"; identity={{"GIT_AUTHOR_NAME":"PostHog Tasks","GIT_AUTHOR_EMAIL":"tasks@posthog.com","GIT_COMMITTER_NAME":"PostHog Tasks","GIT_COMMITTER_EMAIL":"tasks@posthog.com","GIT_AUTHOR_DATE":stamp,"GIT_COMMITTER_DATE":stamp}}
        head=git(["commit-tree",tree],repo,data=P["message"].encode(),extra=identity).decode().strip(); git(["update-ref","refs/publication-artifact/head",head],repo)
        bundle=export/"publication.bundle"; git(["bundle","create",str(bundle),"refs/publication-artifact/head"],repo)
        if bundle.is_symlink() or not bundle.is_file() or bundle.stat().st_size>L["bundle"]: bad("oversized publication bundle")
        os.chmod(bundle,0o600); print(json.dumps({{"bundle_path":str(bundle),"artifact_head_sha":head}}))
        """
    )


def build_publication_bundle(plan: PublicationBundlePlan) -> PublicationBundle:
    if plan.workspace_path.is_symlink() or plan.export_root.is_symlink():
        raise PublicationBundleError("Publication paths are unsafe")
    directory = Path(tempfile.mkdtemp(prefix="publication-script-", dir=plan.export_root))
    # Publication staging must be private to the worker process.
    os.chmod(  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        directory, 0o700
    )
    script = directory / "normalize.py"
    script.write_text(build_publication_bundle_script(plan), encoding="utf-8")
    # The private helper must remain executable by the worker.
    os.chmod(  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        script, 0o700
    )
    try:
        output = subprocess.run(
            [sys.executable, str(script)],
            cwd=directory,
            env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
            capture_output=True,
            check=True,
            timeout=plan.limits.command_timeout_seconds * 4,
            text=True,
        ).stdout
        result = json.loads(output)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as err:
        raise PublicationBundleError("Trusted publication normalization failed") from err
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    bundle = Path(result.get("bundle_path", ""))
    if (
        not bundle.is_absolute()
        or bundle.is_symlink()
        or not bundle.is_file()
        or bundle.parent.parent != plan.export_root.resolve(strict=True)
    ):
        raise PublicationBundleError("Publication normalization returned an unsafe path")
    return PublicationBundle(
        bundle_path=bundle,
        artifact_head_sha=str(result.get("artifact_head_sha", "")),
        byte_count=bundle.stat().st_size,
        export_directory=bundle.parent,
    )


def validate_publication_bundle(payload: bytes, plan: PublicationBundlePlan) -> ValidatedPublicationBundle:
    if not payload or len(payload) > plan.limits.max_bundle_bytes:
        raise PublicationBundleError("Publication bundle size is invalid")
    _validate_pack_header(payload)
    with tempfile.TemporaryDirectory(prefix="publication-validate-") as raw:
        directory = Path(raw)
        # Bundle validation handles untrusted content in an owner-only workspace.
        os.chmod(  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
            directory, 0o700
        )
        bundle = directory / "publication.bundle"
        bundle.write_bytes(payload)
        os.chmod(bundle, 0o600)
        repository = directory / "artifact.git"
        _run_git(["init", "--bare", str(repository)], cwd=directory, limits=plan.limits)
        _run_git(["bundle", "verify", str(bundle)], cwd=repository, limits=plan.limits)
        heads = _run_git(["bundle", "list-heads", str(bundle)], cwd=repository, limits=plan.limits).splitlines()
        if len(heads) != 1 or heads[0].split()[-1:] != [b"refs/publication-artifact/head"]:
            raise PublicationBundleError("Publication bundle head is invalid")
        head = heads[0].split()[0].decode()
        _run_git(["bundle", "unbundle", str(bundle)], cwd=repository, limits=plan.limits)
        parents = _run_git(["rev-list", "--parents", "-n", "1", head], cwd=repository, limits=plan.limits).split()
        if parents != [head.encode()]:
            raise PublicationBundleError("Publication artifact has an unexpected parent")
        artifact = _manifest(repository, head, plan)
    expected = {
        "version": 1,
        "repository": plan.repository,
        "base_commit": plan.base_commit,
        "commit_message": plan.commit_message,
        "commit_timestamp": plan.commit_timestamp,
    }
    if any(artifact.get(key) != value for key, value in expected.items()):
        raise PublicationBundleError("Publication artifact does not match its trusted plan")
    base_tree = artifact.get("base_tree")
    head_tree = artifact.get("head_tree")
    items = artifact.get("operations")
    if (
        not isinstance(base_tree, str)
        or not re.fullmatch(r"[0-9a-f]{40}", base_tree)
        or not isinstance(head_tree, str)
        or not re.fullmatch(r"[0-9a-f]{40}", head_tree)
        or not isinstance(items, list)
        or not items
        or len(items) > plan.limits.max_changed_files
    ):
        raise PublicationBundleError("Publication artifact manifest is invalid")
    operations: list[NormalizedTreeOperation] = []
    total = 0
    previous = ""
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or item["path"] <= previous:
            raise PublicationBundleError("Publication operation is malformed")
        path = item["path"]
        previous = path
        validate_bundle_path_and_text(path=path, text="")
        status = item.get("status")
        mode = item.get("mode")
        if mode not in _SAFE_MODES:
            raise PublicationBundleError("Publication operation mode is unsafe")
        if status == "delete" and set(item) == {"path", "status", "mode"}:
            operations.append(NormalizedTreeOperation(path=path, mode=mode, content=None))
            continue
        text = item.get("text")
        object_id = item.get("object_id")
        if (
            status != "upsert"
            or set(item) != {"path", "status", "mode", "object_id", "text"}
            or not isinstance(text, str)
        ):
            raise PublicationBundleError("Publication operation is malformed")
        validate_bundle_path_and_text(path=path, text=text)
        content = text.encode()
        total += len(content)
        expected_object = (
            hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
                b"blob " + str(len(content)).encode() + b"\0" + content
            ).hexdigest()
        )
        if (
            object_id != expected_object
            or len(content) > plan.limits.max_blob_bytes
            or total > plan.limits.max_total_bytes
        ):
            raise PublicationBundleError("Publication operation content is invalid")
        operations.append(NormalizedTreeOperation(path=path, mode=mode, content=content))
    return ValidatedPublicationBundle(
        artifact_head_sha=head,
        base_tree_sha=base_tree,
        head_tree_sha=head_tree,
        operations=tuple(operations),
    )
