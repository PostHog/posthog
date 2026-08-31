"""Build and validate deterministic, credential-free Git publication artifacts.

The artifact is intentionally a root Git commit rather than a commit on the
protected branch.  A trusted GitHub transport later materializes the verified
operations as the one-parent publication commit.  This keeps the artifact
self-contained while a worker has no trusted clone of the protected base.
"""

from __future__ import annotations

import os
import re
import sys
import json
import stat
import shutil
import difflib
import hashlib
import resource
import tempfile
import subprocess
from collections.abc import Callable
from pathlib import Path
from textwrap import dedent
from uuid import uuid4

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.publication_base import TrustedBaseManifest


class PublicationBundleError(ValueError):
    """The sandbox workspace or received artifact is unsafe for publication."""


@frozen
class PublicationBundleLimits:
    max_bundle_bytes: int = 20 * 1024 * 1024
    max_file_bytes: int = 512 * 1024
    max_total_changed_bytes: int = 2 * 1024 * 1024
    max_changed_files: int = 200
    max_path_bytes: int = 240
    max_diff_bytes: int = 2 * 1024 * 1024
    command_timeout_seconds: int = 15


@frozen
class PublicationBundlePlan:
    workspace_path: Path
    export_root: Path
    repository: str
    base_commit: str
    commit_message: str
    author_name: str
    author_email: str
    commit_timestamp: int
    pr_title: str
    pr_body: str
    limits: PublicationBundleLimits = PublicationBundleLimits()

    def __post_init__(self) -> None:
        if not self.workspace_path.is_absolute() or not self.export_root.is_absolute():
            raise PublicationBundleError("workspace_path and export_root must be absolute server paths")
        if not re.fullmatch(r"[0-9a-f]{40}", self.base_commit):
            raise PublicationBundleError("base_commit must be a protected hexadecimal object id")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise PublicationBundleError("repository must be a server-owned owner/name")
        if not isinstance(self.commit_timestamp, int) or not 0 < self.commit_timestamp < 2**31:
            raise PublicationBundleError("commit_timestamp must be a persisted Unix timestamp")
        if any(
            value <= 0
            for value in (
                self.limits.max_bundle_bytes,
                self.limits.max_file_bytes,
                self.limits.max_total_changed_bytes,
                self.limits.max_changed_files,
                self.limits.max_path_bytes,
                self.limits.max_diff_bytes,
                self.limits.command_timeout_seconds,
            )
        ):
            raise PublicationBundleError("publication limits must be positive")
        for value, name, maximum in (
            (self.commit_message, "commit_message", 500),
            (self.author_name, "author_name", 160),
            (self.author_email, "author_email", 254),
            (self.pr_title, "pr_title", 256),
            (self.pr_body, "pr_body", 20_000),
        ):
            if not value or "\x00" in value or len(value.encode("utf-8")) > maximum:
                raise PublicationBundleError(f"invalid server-owned {name}")


@frozen
class CanonicalFile:
    path: str
    mode: str
    object_id: str | None
    status: str
    byte_count: int


@frozen
class CanonicalTextBlob:
    path: str
    object_id: str
    text: str


@frozen
class PublicationBundle:
    bundle_path: Path
    base_commit: str
    head_commit: str
    byte_count: int
    export_directory: Path


@frozen
class ValidatedPublicationBundle:
    base_commit: str
    head_commit: str
    parent_commits: tuple[str, ...]
    files: tuple[CanonicalFile, ...]
    added_text_blobs: tuple[CanonicalTextBlob, ...]
    unified_diff: str
    commit_message: str
    pr_title: str
    pr_body: str


@frozen
class PublicationBundleInspection:
    head_commit: str
    changed_paths: tuple[str, ...]


@frozen
class _ValidatedWorkspace:
    workspace_path: Path
    export_root: Path


_SAFE_MODES = {"100644", "100755"}
_GENERATED_PARTS = frozenset({"node_modules", "__pycache__", "dist", "build", ".next", ".git"})
_GENERATED_SUFFIXES = (".pyc", ".pyo", ".so", ".a", ".o", ".class", ".dll", ".dylib", ".exe", ".min.js")
_SECRET = re.compile(r"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
_ARTIFACT_OBJECT_COUNT = 3


def _safe_git_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_CONFIG_COUNT": "5",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_CONFIG_KEY_1": "core.hooksPath",
        "GIT_CONFIG_VALUE_1": os.devnull,
        "GIT_CONFIG_KEY_2": "core.attributesFile",
        "GIT_CONFIG_VALUE_2": os.devnull,
        "GIT_CONFIG_KEY_3": "core.excludesFile",
        "GIT_CONFIG_VALUE_3": os.devnull,
        "GIT_CONFIG_KEY_4": "commit.gpgSign",
        "GIT_CONFIG_VALUE_4": "false",
    }


def _artifact_manifest_maximum(limits: PublicationBundleLimits) -> int:
    return min(
        limits.max_bundle_bytes,
        limits.max_total_changed_bytes + limits.max_changed_files * (limits.max_path_bytes + 200) + 25_000,
    )


def _git_import_resource_limiter(limits: PublicationBundleLimits) -> Callable[[], None]:
    expanded_limit = _artifact_manifest_maximum(limits) + 64 * 1024
    memory_limit = max(256 * 1024 * 1024, expanded_limit * 16)
    file_limit = max(limits.max_bundle_bytes, expanded_limit) + 2 * 1024 * 1024

    def apply_limits() -> None:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for kind, requested in (
            (resource.RLIMIT_CPU, limits.command_timeout_seconds),
            (resource.RLIMIT_FSIZE, file_limit),
            (resource.RLIMIT_NOFILE, 64),
        ):
            _soft, hard = resource.getrlimit(kind)
            bounded = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
            resource.setrlimit(kind, (bounded, bounded))
        if sys.platform != "darwin":
            _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            bounded_memory = memory_limit if hard == resource.RLIM_INFINITY else min(memory_limit, hard)
            resource.setrlimit(resource.RLIMIT_AS, (bounded_memory, bounded_memory))

    return apply_limits


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    timeout: int,
    input_bytes: bytes | None = None,
    import_limits: PublicationBundleLimits | None = None,
) -> bytes:
    try:
        return subprocess.run(
            ["/usr/bin/git", "--no-optional-locks", "-c", "diff.external=", "-c", "core.pager=cat", *args],
            cwd=cwd,
            env=_safe_git_environment(),
            input=input_bytes,
            capture_output=True,
            check=True,
            timeout=timeout,
            preexec_fn=_git_import_resource_limiter(import_limits) if import_limits is not None else None,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise PublicationBundleError("safe Git command failed") from error


def _strict_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise PublicationBundleError("server path must be absolute")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except OSError as error:
            raise PublicationBundleError("server path is missing") from error
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise PublicationBundleError("server path contains a symlink or non-directory")
    return path.resolve(strict=True)


def _regular(path: Path, maximum: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise PublicationBundleError("unsafe Git control file") from error
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > maximum:
            raise PublicationBundleError("unsafe Git control file")
        content = bytearray()
        while len(content) < details.st_size:
            chunk = os.read(descriptor, min(64 * 1024, details.st_size - len(content)))
            if not chunk:
                raise PublicationBundleError("Git control file changed during read")
            content.extend(chunk)
        if os.read(descriptor, 1) or os.fstat(descriptor).st_size != details.st_size:
            raise PublicationBundleError("Git control file changed during read")
        return bytes(content)
    finally:
        os.close(descriptor)


def _validate_path(path: str, limits: PublicationBundleLimits) -> None:
    try:
        encoded = path.encode("utf-8", "strict")
    except UnicodeError as error:
        raise PublicationBundleError("publication path is not UTF-8") from error
    pieces = path.split("/")
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(piece in {"", ".", ".."} for piece in pieces)
    ):
        raise PublicationBundleError("malformed publication path")
    if (
        len(encoded) > limits.max_path_bytes
        or any(piece in _GENERATED_PARTS for piece in pieces)
        or path.endswith(_GENERATED_SUFFIXES)
    ):
        raise PublicationBundleError("generated or oversized publication path")


def _scan_text(value: str) -> None:
    if _SECRET.search(value):
        raise PublicationBundleError("publication artifact contains a credential-like value")


def _validate_workspace(plan: PublicationBundlePlan) -> _ValidatedWorkspace:
    workspace = _strict_directory(plan.workspace_path)
    root = _strict_directory(plan.export_root)
    git_dir = workspace / ".git"
    if not git_dir.exists() or stat.S_ISLNK(os.lstat(git_dir).st_mode) or not git_dir.is_dir():
        raise PublicationBundleError("Git worktree indirection is not allowed")
    config = _regular(git_dir / "config", 64 * 1024)
    section: str | None = None
    allowed = {
        "core": {
            "repositoryformatversion",
            "filemode",
            "bare",
            "logallrefupdates",
            "symlinks",
            "ignorecase",
            "precomposeunicode",
        },
        "extensions": {"objectformat"},
    }
    for line in config.decode("utf-8", "strict").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        header = re.fullmatch(r"\[([A-Za-z]+)\]", line)
        if header:
            section = header.group(1).lower()
            if section not in allowed:
                raise PublicationBundleError("local Git config is not minimal")
            continue
        if section is None or "=" not in line:
            raise PublicationBundleError("local Git config is malformed")
        key = line.split("=", 1)[0].strip().lower()
        if key not in allowed[section]:
            raise PublicationBundleError("local Git config has a command surface")
    for path in (git_dir / "HEAD", git_dir / "index"):
        if path.exists():
            _regular(path, 20 * 1024 * 1024)
    packed_refs = git_dir / "packed-refs"
    if packed_refs.exists() and b"refs/replace/" in _regular(packed_refs, 10 * 1024 * 1024):
        raise PublicationBundleError("workspace contains replace refs")
    for path in (git_dir / "objects", git_dir / "objects" / "info", git_dir / "refs"):
        if not path.exists() or stat.S_ISLNK(os.lstat(path).st_mode) or not path.is_dir():
            raise PublicationBundleError("unsafe Git object topology")
    for dangerous in (
        git_dir / "objects" / "info" / "alternates",
        git_dir / "info" / "grafts",
        git_dir / "shallow",
        git_dir / "modules",
        workspace / ".gitmodules",
        git_dir / "refs" / "replace",
    ):
        if dangerous.exists() or dangerous.is_symlink():
            raise PublicationBundleError("workspace contains an unsafe Git topology")
    return _ValidatedWorkspace(workspace_path=workspace, export_root=root)


def _make_export_directory(root: Path) -> Path:
    directory = Path(tempfile.mkdtemp(prefix=f"publication-{uuid4().hex}-", dir=root))
    # Owner-only permissions protect staged publication material.
    os.chmod(  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        directory, 0o700
    )
    if stat.S_ISLNK(os.lstat(directory).st_mode) or directory.resolve(strict=True).parent != root:
        raise PublicationBundleError("export directory escaped trusted root")
    return directory


def build_publication_bundle_script(plan: PublicationBundlePlan, script_path: Path) -> str:
    """Return fixed server code for the activity to write and execute after agent stop."""
    if not script_path.is_absolute():
        raise PublicationBundleError("script_path must be an absolute server path")
    payload = json.dumps(
        {
            "workspace_path": str(plan.workspace_path),
            "export_root": str(plan.export_root),
            "repository": plan.repository,
            "base_commit": plan.base_commit,
            "commit_message": plan.commit_message,
            "author_name": plan.author_name,
            "author_email": plan.author_email,
            "commit_timestamp": plan.commit_timestamp,
            "pr_title": plan.pr_title,
            "pr_body": plan.pr_body,
            "limits": {
                "max_bundle_bytes": plan.limits.max_bundle_bytes,
                "max_file_bytes": plan.limits.max_file_bytes,
                "max_total_changed_bytes": plan.limits.max_total_changed_bytes,
                "max_changed_files": plan.limits.max_changed_files,
                "max_path_bytes": plan.limits.max_path_bytes,
                "max_diff_bytes": plan.limits.max_diff_bytes,
                "command_timeout_seconds": plan.limits.command_timeout_seconds,
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return dedent(f"""\
        import json, os, re, shutil, stat, subprocess, sys, tempfile, uuid
        from pathlib import Path
        P=json.loads({payload!r}); L=P["limits"]
        E={{"PATH":"/usr/bin:/bin","HOME":"/nonexistent","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null","GIT_ATTR_NOSYSTEM":"1","GIT_TERMINAL_PROMPT":"0","GIT_ALLOW_PROTOCOL":"","GIT_CONFIG_COUNT":"5","GIT_CONFIG_KEY_0":"core.fsmonitor","GIT_CONFIG_VALUE_0":"false","GIT_CONFIG_KEY_1":"core.hooksPath","GIT_CONFIG_VALUE_1":"/dev/null","GIT_CONFIG_KEY_2":"core.attributesFile","GIT_CONFIG_VALUE_2":"/dev/null","GIT_CONFIG_KEY_3":"core.excludesFile","GIT_CONFIG_VALUE_3":"/dev/null","GIT_CONFIG_KEY_4":"commit.gpgSign","GIT_CONFIG_VALUE_4":"false"}}
        safe_modes={{"100644","100755"}}; generated={{"node_modules","__pycache__","dist","build",".next",".git"}}; suffixes=(".pyc",".pyo",".so",".a",".o",".class",".dll",".dylib",".exe",".min.js")
        secret=re.compile(r"(?:github_pat_[A-Za-z0-9_]{{20,}}|gh[pousr]_[A-Za-z0-9]{{20,}}|AKIA[0-9A-Z]{{16}})")
        def bad(x): raise SystemExit(x)
        def regular(p,n):
            try: d=os.open(p,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)); s=os.fstat(d)
            except OSError: bad("unsafe Git control file")
            try:
                if not stat.S_ISREG(s.st_mode) or s.st_size>n: bad("unsafe Git control file")
                content=bytearray()
                while len(content)<s.st_size:
                    chunk=os.read(d,min(65536,s.st_size-len(content)))
                    if not chunk: bad("Git control file changed during read")
                    content.extend(chunk)
                if os.read(d,1) or os.fstat(d).st_size!=s.st_size: bad("Git control file changed during read")
                return bytes(content)
            finally: os.close(d)
        def directory(raw):
            p=Path(raw); c=Path(p.anchor)
            if not p.is_absolute(): bad("relative server path")
            for x in p.parts[1:]:
                c/=x
                try: m=os.lstat(c).st_mode
                except OSError: bad("missing server path")
                if stat.S_ISLNK(m) or not stat.S_ISDIR(m): bad("unsafe server path")
            return p.resolve(strict=True)
        def okpath(x):
            try: b=x.encode("utf-8","strict")
            except UnicodeError: bad("non-UTF8 path")
            q=x.split("/")
            if not x or x.startswith("/") or "\\\\" in x or any(y in {{"",".",".."}} for y in q) or len(b)>L["max_path_bytes"] or any(y in generated for y in q) or x.endswith(suffixes): bad("unsafe path")
        def read_workspace_file(root,rel):
            okpath(rel); directory_fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0))
            try:
                parts=rel.split("/")
                for part in parts[:-1]:
                    next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0),dir_fd=directory_fd)
                    os.close(directory_fd); directory_fd=next_fd
                file_fd=os.open(parts[-1],os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=directory_fd)
                try:
                    details=os.fstat(file_fd)
                    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_size>L["max_file_bytes"]: bad("unsafe file")
                    chunks=[]; remaining=details.st_size
                    while remaining:
                        chunk=os.read(file_fd,min(65536,remaining))
                        if not chunk: bad("workspace file changed during read")
                        chunks.append(chunk); remaining-=len(chunk)
                    return b"".join(chunks),details.st_mode
                finally: os.close(file_fd)
            finally: os.close(directory_fd)
        def git(args,gd,wd=None,index=None,data=None,env=None):
            e=dict(E); e["GIT_DIR"]=str(gd)
            if wd: e["GIT_WORK_TREE"]=str(wd)
            if index: e["GIT_INDEX_FILE"]=str(index)
            if env: e.update(env)
            try: return subprocess.run(["/usr/bin/git","--no-optional-locks","-c","diff.external=","-c","core.pager=cat",*args],cwd=gd,env=e,input=data,capture_output=True,check=True,timeout=L["command_timeout_seconds"]).stdout
            except Exception: bad("safe Git command failed")
        def source_head(gd):
            raw=regular(gd/"HEAD",4096).decode("ascii","strict").strip()
            if re.fullmatch(r"[0-9a-f]{{40,64}}",raw): return raw
            m=re.fullmatch(r"ref: (refs/heads/[A-Za-z0-9._/-]+)",raw)
            if not m or ".." in m.group(1): bad("unsafe HEAD")
            ref=gd/m.group(1)
            if ref.exists(): return regular(ref,4096).decode("ascii","strict").strip()
            bad("packed source refs are not supported")
        w,root=directory(P["workspace_path"]),directory(P["export_root"]); gd=w/".git"
        if not gd.is_dir() or gd.is_symlink(): bad("Git indirection")
        cfg=regular(gd/"config",65536).decode("utf-8","strict"); section=None; allowed={{"core":{{"repositoryformatversion","filemode","bare","logallrefupdates","symlinks","ignorecase","precomposeunicode"}},"extensions":{{"objectformat"}}}}
        for line in cfg.splitlines():
            line=line.strip()
            if not line or line.startswith(("#",";")): continue
            h=re.fullmatch(r"\\[([A-Za-z]+)\\]",line)
            if h:
                section=h.group(1).lower()
                if section not in allowed: bad("nonminimal config")
            elif section is None or "=" not in line or line.split("=",1)[0].strip().lower() not in allowed[section]: bad("unsafe config")
        for x in [gd/"objects",gd/"objects"/"info",gd/"refs"]:
            if not x.is_dir() or x.is_symlink(): bad("unsafe object topology")
        packed=gd/"packed-refs"
        if packed.exists() and b"refs/replace/" in regular(packed,10*1024*1024): bad("replace refs")
        for x in [gd/"objects"/"info"/"alternates",gd/"info"/"grafts",gd/"shallow",gd/"modules",w/".gitmodules",gd/"refs"/"replace"]:
            if x.exists() or x.is_symlink(): bad("unsafe Git topology")
        head=source_head(gd); base=P["base_commit"]
        export=Path(tempfile.mkdtemp(prefix="publication-"+uuid.uuid4().hex+"-",dir=root)); os.chmod(export,0o700)
        try:
            isolated=export/"isolated.git"; git(["init","--bare",str(isolated)],export)
            E["GIT_ALTERNATE_OBJECT_DIRECTORIES"]=str(gd/"objects")
            git(["cat-file","-e",base+"^{{commit}}"],isolated); git(["cat-file","-e",head+"^{{commit}}"],isolated); git(["update-ref","refs/source/head",head],isolated)
            if subprocess.run(["/usr/bin/git","--git-dir",str(isolated),"merge-base","--is-ancestor",base,"refs/source/head"],env=E,capture_output=True,timeout=L["command_timeout_seconds"]).returncode: bad("head is not descendant of protected base")
            for row in git(["rev-list","--parents",base+"..refs/source/head"],isolated).splitlines():
                if len(row.split())!=2: bad("agent merge history")
            index=export/"source.index"; git(["read-tree",base],isolated,w,index)
            changes=set(x.decode("utf-8","strict") for x in git(["diff","--name-only","-z","--no-ext-diff","--no-textconv",base],isolated,w,index).rstrip(b"\\0").split(b"\\0") if x)
            changes.update(x.decode("utf-8","strict") for x in git(["ls-files","--others","-z"],isolated,w,index).rstrip(b"\\0").split(b"\\0") if x)
            if len(changes)>L["max_changed_files"]: bad("too many changed paths")
            operations=[]; total=0
            for rel in sorted(changes):
                try: data,mode=read_workspace_file(w,rel)
                except FileNotFoundError: operations.append({{"path":rel,"status":"deleted"}}); continue
                except OSError: bad("unreadable workspace path")
                if b"\\0" in data: bad("unsafe file")
                try: text=data.decode("utf-8","strict")
                except UnicodeError: bad("non-text file")
                if secret.search(text): bad("credential-like value")
                total+=len(data)
                if total>L["max_total_changed_bytes"]: bad("changed bytes limit")
                oid=git(["hash-object","-w","--no-filters","--stdin"],isolated,data=data).decode().strip()
                operations.append({{"path":rel,"status":"upsert","mode":"100755" if mode&stat.S_IXUSR else "100644","object_id":oid,"text":text}})
            base_tree=git(["rev-parse",base+"^{{tree}}"],isolated).decode().strip()
            manifest={{"version":1,"repository":P["repository"],"base_commit":base,"base_tree":base_tree,"operations":operations,"commit_message":P["commit_message"],"author_name":P["author_name"],"author_email":P["author_email"],"commit_timestamp":P["commit_timestamp"],"pr_title":P["pr_title"],"pr_body":P["pr_body"]}}
            payload=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
            manifest_oid=git(["hash-object","-w","--no-filters","--stdin"],isolated,data=payload).decode().strip()
            artifact_index=export/"artifact.index"; git(["update-index","--add","--cacheinfo","100644,"+manifest_oid+",manifest.json"],isolated,index=artifact_index)
            tree=git(["write-tree"],isolated,index=artifact_index).decode().strip(); stamp=str(P["commit_timestamp"])+" +0000"; identity={{"GIT_AUTHOR_NAME":P["author_name"],"GIT_AUTHOR_EMAIL":P["author_email"],"GIT_COMMITTER_NAME":P["author_name"],"GIT_COMMITTER_EMAIL":P["author_email"],"GIT_AUTHOR_DATE":stamp,"GIT_COMMITTER_DATE":stamp}}
            head=git(["commit-tree",tree],isolated,data=P["commit_message"].encode(),env=identity).decode().strip(); git(["update-ref","refs/publication-artifact/head",head],isolated)
            bundle=export/"publication.bundle"; git(["bundle","create",str(bundle),"refs/publication-artifact/head"],isolated)
            if not bundle.is_file() or bundle.is_symlink() or bundle.stat().st_size>L["max_bundle_bytes"]: bad("bundle limit")
            os.chmod(bundle,0o600); print(json.dumps({{"bundle_path":str(bundle),"head_commit":head}}))
        except BaseException:
            shutil.rmtree(export,ignore_errors=True); raise
        """)


def build_publication_bundle(plan: PublicationBundlePlan) -> PublicationBundle:
    validated_workspace = _validate_workspace(plan)
    script_directory = _make_export_directory(validated_workspace.export_root)
    script = script_directory / "normalize.py"
    script.write_text(build_publication_bundle_script(plan, script), encoding="utf-8")
    # Owner-only permissions protect the trusted normalization script.
    os.chmod(script, 0o700)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    try:
        output = subprocess.run(
            [sys.executable, str(script)],
            cwd=script_directory,
            env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
            capture_output=True,
            check=True,
            timeout=plan.limits.command_timeout_seconds * 4,
            text=True,
        ).stdout
        result = json.loads(output)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise PublicationBundleError("trusted normalization script failed") from error
    finally:
        shutil.rmtree(script_directory, ignore_errors=True)
    bundle = Path(result.get("bundle_path", ""))
    if (
        not bundle.is_absolute()
        or bundle.parent.parent != validated_workspace.export_root
        or bundle.is_symlink()
        or not bundle.is_file()
    ):
        raise PublicationBundleError("normalization returned an unsafe bundle path")
    return PublicationBundle(
        bundle_path=bundle,
        base_commit=plan.base_commit,
        head_commit=str(result.get("head_commit", "")),
        byte_count=bundle.stat().st_size,
        export_directory=bundle.parent,
    )


def _artifact_manifest(repository: Path, head: str, limits: PublicationBundleLimits) -> dict[str, object]:
    tree = (
        _run_git(["ls-tree", "-r", "-z", head], cwd=repository, timeout=limits.command_timeout_seconds)
        .rstrip(b"\0")
        .split(b"\0")
    )
    if len(tree) != 1 or not tree[0].startswith(b"100644 blob ") or not tree[0].endswith(b"\tmanifest.json"):
        raise PublicationBundleError("artifact must contain exactly canonical manifest.json")
    object_id = tree[0].split(b" ", 2)[2].split(b"\t", 1)[0].decode("ascii")
    maximum = _artifact_manifest_maximum(limits)
    size = _run_git(["cat-file", "-s", object_id], cwd=repository, timeout=limits.command_timeout_seconds)
    if not size.strip().isdigit() or int(size) > maximum:
        raise PublicationBundleError("artifact manifest exceeds its byte limit")
    try:
        value = json.loads(
            _run_git(["cat-file", "blob", object_id], cwd=repository, timeout=limits.command_timeout_seconds)
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationBundleError("artifact manifest is malformed") from error
    if not isinstance(value, dict):
        raise PublicationBundleError("artifact manifest is malformed")
    return value


def _validate_bundle_pack_header(bundle_bytes: bytes) -> None:
    marker = b"\n\nPACK"
    marker_index = bundle_bytes.find(marker)
    if marker_index < 0:
        raise PublicationBundleError("bundle has no canonical pack payload")
    pack = bundle_bytes[marker_index + 2 :]
    if len(pack) < 12 or pack[:4] != b"PACK":
        raise PublicationBundleError("bundle has an invalid pack header")
    version = int.from_bytes(pack[4:8], "big")
    object_count = int.from_bytes(pack[8:12], "big")
    if version not in {2, 3} or object_count != _ARTIFACT_OBJECT_COUNT:
        raise PublicationBundleError("bundle must contain exactly the canonical artifact objects")


def _validate_imported_pack(repository: Path, head: str, limits: PublicationBundleLimits) -> None:
    indexes = list((repository / "objects" / "pack").glob("*.idx"))
    packs = list((repository / "objects" / "pack").glob("*.pack"))
    if len(indexes) != 1 or len(packs) != 1:
        raise PublicationBundleError("bundle import produced an invalid object store")
    output = _run_git(
        ["verify-pack", "-v", str(indexes[0])],
        cwd=repository,
        timeout=limits.command_timeout_seconds,
        import_limits=limits,
    )
    imported: dict[str, int] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 5 or not re.fullmatch(rb"[0-9a-f]{40}", fields[0]):
            continue
        if fields[1] not in {b"blob", b"commit", b"tree"} or not fields[2].isdigit():
            raise PublicationBundleError("bundle contains a non-canonical Git object")
        object_id = fields[0].decode("ascii")
        if object_id in imported:
            raise PublicationBundleError("bundle contains a duplicate Git object")
        imported[object_id] = int(fields[2])
    reachable = {
        line.split(maxsplit=1)[0].decode("ascii")
        for line in _run_git(
            ["rev-list", "--objects", head],
            cwd=repository,
            timeout=limits.command_timeout_seconds,
            import_limits=limits,
        ).splitlines()
    }
    expanded_limit = _artifact_manifest_maximum(limits) + 64 * 1024
    if (
        len(imported) != _ARTIFACT_OBJECT_COUNT
        or set(imported) != reachable
        or sum(imported.values()) > expanded_limit
        or max(imported.values(), default=0) > _artifact_manifest_maximum(limits)
    ):
        raise PublicationBundleError("bundle object closure exceeds its canonical limits")


def inspect_publication_bundle(bundle_bytes: bytes, plan: PublicationBundlePlan) -> PublicationBundleInspection:
    """Safely extract bounded changed paths before fetching their trusted base text."""
    if not bundle_bytes or len(bundle_bytes) > plan.limits.max_bundle_bytes:
        raise PublicationBundleError("bundle exceeds its byte limit")
    _validate_bundle_pack_header(bundle_bytes)
    with tempfile.TemporaryDirectory(prefix="publication-inspect-") as raw:
        directory = Path(raw)
        # Owner-only permissions protect staged publication material.
        os.chmod(  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
            directory, 0o700
        )
        bundle = directory / "publication.bundle"
        bundle.write_bytes(bundle_bytes)
        os.chmod(bundle, 0o600)
        repository = directory / "artifact.git"
        _run_git(["init", "--bare", str(repository)], cwd=directory, timeout=plan.limits.command_timeout_seconds)
        _run_git(["bundle", "verify", str(bundle)], cwd=repository, timeout=plan.limits.command_timeout_seconds)
        heads = _run_git(
            ["bundle", "list-heads", str(bundle)], cwd=repository, timeout=plan.limits.command_timeout_seconds
        ).splitlines()
        if len(heads) != 1 or heads[0].split()[-1:] != [b"refs/publication-artifact/head"]:
            raise PublicationBundleError("bundle must expose exactly one artifact head")
        head = heads[0].split()[0].decode("ascii")
        _run_git(
            ["bundle", "unbundle", str(bundle)],
            cwd=repository,
            timeout=plan.limits.command_timeout_seconds,
            import_limits=plan.limits,
        )
        _validate_imported_pack(repository, head, plan.limits)
        if _run_git(
            ["rev-list", "--parents", "-n", "1", head], cwd=repository, timeout=plan.limits.command_timeout_seconds
        ).split() != [head.encode()]:
            raise PublicationBundleError("artifact commit must be a self-contained root")
        identity = _run_git(
            ["show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce%x00%at%x00%ct%x00%B", head],
            cwd=repository,
            timeout=plan.limits.command_timeout_seconds,
        ).split(b"\0", 6)
        if (
            len(identity) != 7
            or tuple(item.decode("utf-8", "strict") for item in identity[:4])
            != (plan.author_name, plan.author_email, plan.author_name, plan.author_email)
            or identity[4:6] != [str(plan.commit_timestamp).encode(), str(plan.commit_timestamp).encode()]
            or identity[6].decode("utf-8", "strict").rstrip("\n") != plan.commit_message
        ):
            raise PublicationBundleError("artifact commit metadata is not server-authored")
        artifact = _artifact_manifest(repository, head, plan.limits)
    expected = {
        "version": 1,
        "repository": plan.repository,
        "base_commit": plan.base_commit,
        "commit_message": plan.commit_message,
        "author_name": plan.author_name,
        "author_email": plan.author_email,
        "commit_timestamp": plan.commit_timestamp,
        "pr_title": plan.pr_title,
        "pr_body": plan.pr_body,
    }
    operations = artifact.get("operations")
    if (
        any(artifact.get(key) != value for key, value in expected.items())
        or not isinstance(operations, list)
        or not operations
        or len(operations) > plan.limits.max_changed_files
    ):
        raise PublicationBundleError("artifact manifest does not match the server command plan")
    paths: list[str] = []
    previous = ""
    for item in operations:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or item["path"] <= previous:
            raise PublicationBundleError("artifact operation is malformed")
        _validate_path(item["path"], plan.limits)
        paths.append(item["path"])
        previous = item["path"]
    return PublicationBundleInspection(head_commit=head, changed_paths=tuple(paths))


def validate_publication_bundle(
    bundle_bytes: bytes, plan: PublicationBundlePlan, base_manifest: TrustedBaseManifest
) -> ValidatedPublicationBundle:
    """Validate a downloaded artifact using the transport-owned GitHub base manifest."""
    inspection = inspect_publication_bundle(bundle_bytes, plan)
    if not bundle_bytes or len(bundle_bytes) > plan.limits.max_bundle_bytes:
        raise PublicationBundleError("bundle exceeds its byte limit")
    _validate_bundle_pack_header(bundle_bytes)
    if (
        base_manifest.repository != plan.repository
        or base_manifest.base_sha != plan.base_commit
        or not re.fullmatch(r"[0-9a-f]{40,64}", base_manifest.tree_sha)
    ):
        raise PublicationBundleError("trusted base manifest does not match protected base")
    with tempfile.TemporaryDirectory(prefix="publication-validate-") as raw:
        directory = Path(raw)
        # Owner-only permissions protect staged publication material.
        os.chmod(  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
            directory, 0o700
        )
        bundle = directory / "publication.bundle"
        bundle.write_bytes(bundle_bytes)
        os.chmod(bundle, 0o600)
        repository = directory / "artifact.git"
        _run_git(["init", "--bare", str(repository)], cwd=directory, timeout=plan.limits.command_timeout_seconds)
        _run_git(["bundle", "verify", str(bundle)], cwd=repository, timeout=plan.limits.command_timeout_seconds)
        heads = _run_git(
            ["bundle", "list-heads", str(bundle)], cwd=repository, timeout=plan.limits.command_timeout_seconds
        ).splitlines()
        if len(heads) != 1 or heads[0].split()[-1:] != [b"refs/publication-artifact/head"]:
            raise PublicationBundleError("bundle must expose exactly one artifact head")
        head = heads[0].split()[0].decode("ascii")
        _run_git(
            ["bundle", "unbundle", str(bundle)],
            cwd=repository,
            timeout=plan.limits.command_timeout_seconds,
            import_limits=plan.limits,
        )
        _validate_imported_pack(repository, head, plan.limits)
        parents = _run_git(
            ["rev-list", "--parents", "-n", "1", head], cwd=repository, timeout=plan.limits.command_timeout_seconds
        ).split()
        if parents != [head.encode()]:
            raise PublicationBundleError("artifact commit must be a self-contained root")
        identity = _run_git(
            ["show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce%x00%at%x00%ct%x00%B", head],
            cwd=repository,
            timeout=plan.limits.command_timeout_seconds,
        ).split(b"\0", 6)
        if (
            len(identity) != 7
            or tuple(item.decode("utf-8", "strict") for item in identity[:4])
            != (plan.author_name, plan.author_email, plan.author_name, plan.author_email)
            or identity[4:6] != [str(plan.commit_timestamp).encode(), str(plan.commit_timestamp).encode()]
            or identity[6].decode("utf-8", "strict").rstrip("\n") != plan.commit_message
        ):
            raise PublicationBundleError("artifact commit metadata is not server-authored")
        artifact = _artifact_manifest(repository, head, plan.limits)
    expected = {
        "version": 1,
        "repository": plan.repository,
        "base_commit": plan.base_commit,
        "base_tree": base_manifest.tree_sha,
        "commit_message": plan.commit_message,
        "author_name": plan.author_name,
        "author_email": plan.author_email,
        "commit_timestamp": plan.commit_timestamp,
        "pr_title": plan.pr_title,
        "pr_body": plan.pr_body,
    }
    operations = artifact.get("operations")
    if any(artifact.get(key) != value for key, value in expected.items()) or not isinstance(operations, list):
        raise PublicationBundleError("artifact manifest does not match the server command plan")
    _scan_text(plan.commit_message)
    _scan_text(plan.pr_title)
    _scan_text(plan.pr_body)
    if not operations or len(operations) > plan.limits.max_changed_files:
        raise PublicationBundleError("artifact has too many changed paths")
    files: list[CanonicalFile] = []
    blobs: list[CanonicalTextBlob] = []
    diff_lines: list[str] = []
    total = 0
    previous = ""
    for item in operations:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise PublicationBundleError("artifact operation is malformed")
        path = item["path"]
        _validate_path(path, plan.limits)
        if path <= previous:
            raise PublicationBundleError("artifact operations must be sorted and unique")
        previous = path
        old = base_manifest.entry_for(path)
        status = item.get("status")
        if status == "deleted":
            if old is None or set(item) != {"path", "status"}:
                raise PublicationBundleError("artifact deletion is invalid")
            old_text = base_manifest.old_text_for(path)
            if old.object_type != "blob" or old.mode not in _SAFE_MODES or old_text is None:
                raise PublicationBundleError("trusted base manifest has an unsafe changed file")
            files.append(CanonicalFile(path=path, mode=old.mode, object_id=None, status="deleted", byte_count=0))
            diff_lines.extend(
                difflib.unified_diff(old_text.splitlines(keepends=True), [], fromfile=f"a/{path}", tofile=f"b/{path}")
            )
            continue
        if (
            status != "upsert"
            or set(item) != {"path", "status", "mode", "object_id", "text"}
            or item.get("mode") not in _SAFE_MODES
            or not isinstance(item.get("object_id"), str)
            or not isinstance(item.get("text"), str)
        ):
            raise PublicationBundleError("artifact update is invalid")
        text = item["text"]
        data = text.encode("utf-8")
        total += len(data)
        if len(data) > plan.limits.max_file_bytes or total > plan.limits.max_total_changed_bytes:
            raise PublicationBundleError("artifact files exceed a byte limit")
        _scan_text(text)
        mode = item["mode"]
        object_id = item["object_id"]
        # Git object IDs use SHA-1 by protocol, not for authentication.
        expected_object_id = (
            hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
                f"blob {len(data)}\0".encode() + data
            ).hexdigest()
        )
        if object_id != expected_object_id:
            raise PublicationBundleError("artifact text does not match its declared blob id")
        if old is None:
            old_text = ""
        else:
            old_text = base_manifest.old_text_for(path)
            if old.object_type != "blob" or old.mode not in _SAFE_MODES or old_text is None:
                raise PublicationBundleError("trusted base manifest has an unsafe changed file")
            if old.object_sha == object_id and old.mode == mode:
                raise PublicationBundleError("artifact contains a no-op update")
        files.append(
            CanonicalFile(
                path=path,
                mode=mode,
                object_id=object_id,
                status="added" if old is None else "modified",
                byte_count=len(data),
            )
        )
        blobs.append(CanonicalTextBlob(path=path, object_id=object_id, text=text))
        diff_lines.extend(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
    diff = "".join(diff_lines)
    if len(diff.encode()) > plan.limits.max_diff_bytes:
        raise PublicationBundleError("artifact diff exceeds its byte limit")
    _scan_text(diff)
    return ValidatedPublicationBundle(
        base_commit=plan.base_commit,
        head_commit=inspection.head_commit,
        parent_commits=(),
        files=tuple(files),
        added_text_blobs=tuple(blobs),
        unified_diff=diff,
        commit_message=plan.commit_message,
        pr_title=plan.pr_title,
        pr_body=plan.pr_body,
    )
