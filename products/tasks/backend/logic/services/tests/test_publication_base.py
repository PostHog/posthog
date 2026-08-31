import json
import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

import pytest

import requests

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority

from products.tasks.backend.logic.services.publication_base import (
    PublicationBaseError,
    PublicationBaseLimits,
    load_trusted_base_manifest,
)


@dataclass(frozen=False)
class _Response:
    status_code: int
    body: object

    def json(self) -> object:
        return self.body


class _GitHubFake:
    def __init__(self, responses: Mapping[tuple[str, str], list[_Response | Exception]]) -> None:
        self.responses = {key: list(value) for key, value in responses.items()}
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def api_request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str | None = None,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, object] | None = None,
        priority: Priority | None = None,
        retry_transient: bool | None = None,
    ) -> _Response:
        kwargs: dict[str, object] = {
            "endpoint": endpoint,
            "params": params,
            "json_body": json_body,
            "priority": priority,
            "retry_transient": retry_transient,
        }
        self.requests.append((method, path, kwargs))
        response = self.responses[(method, path)].pop(0)
        if isinstance(response, Exception):
            raise response
        return response


REPOSITORY = "posthog/posthog"
BASE_SHA = "a" * 40
TREE_SHA = "b" * 40


def _blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def _tree_entry(path: str, content: bytes, *, mode: str = "100644", entry_type: str = "blob") -> dict[str, str]:
    return {"path": path, "mode": mode, "type": entry_type, "sha": _blob_sha(content)}


def _responses(
    entries: list[dict[str, str]], blobs: Mapping[str, bytes]
) -> dict[tuple[str, str], list[_Response | Exception]]:
    responses: dict[tuple[str, str], list[_Response | Exception]] = {
        ("GET", f"/repos/{REPOSITORY}/git/commits/{BASE_SHA}"): [
            _Response(200, {"sha": BASE_SHA, "tree": {"sha": TREE_SHA}})
        ],
        ("GET", f"/repos/{REPOSITORY}/git/trees/{TREE_SHA}"): [
            _Response(200, {"sha": TREE_SHA, "truncated": False, "tree": entries})
        ],
    }
    for object_sha, content in blobs.items():
        responses[("GET", f"/repos/{REPOSITORY}/git/blobs/{object_sha}")] = [
            _Response(200, {"sha": object_sha, "encoding": "base64", "content": base64.b64encode(content).decode()})
        ]
    return responses


def test_manifest_captures_additions_modifications_and_deletions_without_reading_unrequested_blobs() -> None:
    changed = b"old changed\n"
    deleted = b"old deleted\n"
    untouched = b"private but untouched\n"
    entries = [
        _tree_entry("changed.txt", changed),
        _tree_entry("deleted.txt", deleted, mode="100755"),
        _tree_entry("untouched.txt", untouched),
    ]
    fake = _GitHubFake(_responses(entries, {_blob_sha(changed): changed, _blob_sha(deleted): deleted}))

    manifest = load_trusted_base_manifest(
        fake,
        repository=REPOSITORY,
        base_sha=BASE_SHA,
        changed_paths=("added.txt", "changed.txt", "deleted.txt"),
    )

    assert manifest.repository == REPOSITORY
    assert manifest.base_sha == BASE_SHA
    assert manifest.tree_sha == TREE_SHA
    assert manifest.entry_for("added.txt") is None
    changed_entry = manifest.entry_for("changed.txt")
    deleted_entry = manifest.entry_for("deleted.txt")
    assert changed_entry is not None
    assert deleted_entry is not None
    assert changed_entry.mode == "100644"
    assert deleted_entry.mode == "100755"
    assert manifest.old_text_for("added.txt") is None
    assert manifest.old_text_for("changed.txt") == "old changed\n"
    assert manifest.old_text_for("deleted.txt") == "old deleted\n"
    assert manifest.old_text_for("untouched.txt") is None
    assert [path for _method, path, _kwargs in fake.requests if "/git/blobs/" in path] == [
        f"/repos/{REPOSITORY}/git/blobs/{_blob_sha(changed)}",
        f"/repos/{REPOSITORY}/git/blobs/{_blob_sha(deleted)}",
    ]
    assert all(method == "GET" for method, _path, _kwargs in fake.requests)
    assert all(
        kwargs["priority"] is Priority.CRITICAL and kwargs["retry_transient"] is False
        for _method, _path, kwargs in fake.requests
    )
    assert all(kwargs.get("params") is None for _method, _path, kwargs in fake.requests)


def test_manifest_walks_only_requested_path_topology_without_recursive_tree_reads() -> None:
    source_tree_sha = "c" * 40
    feature_tree_sha = "d" * 40
    unrelated_tree_sha = "e" * 40
    content = b"old target\n"
    sibling_content = b"old sibling\n"
    target_sha = _blob_sha(content)
    sibling_sha = _blob_sha(sibling_content)
    unrelated_entries = [_tree_entry(f"unrelated-{index}.txt", b"x") for index in range(20_001)]
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/commits/{BASE_SHA}"): [
                _Response(200, {"sha": BASE_SHA, "tree": {"sha": TREE_SHA}})
            ],
            ("GET", f"/repos/{REPOSITORY}/git/trees/{TREE_SHA}"): [
                _Response(
                    200,
                    {
                        "sha": TREE_SHA,
                        "truncated": False,
                        "tree": [
                            {"path": "src", "mode": "040000", "type": "tree", "sha": source_tree_sha},
                            {"path": "huge-unrelated", "mode": "040000", "type": "tree", "sha": unrelated_tree_sha},
                        ],
                    },
                )
            ],
            ("GET", f"/repos/{REPOSITORY}/git/trees/{source_tree_sha}"): [
                _Response(
                    200,
                    {
                        "sha": source_tree_sha,
                        "truncated": False,
                        "tree": [{"path": "feature", "mode": "040000", "type": "tree", "sha": feature_tree_sha}],
                    },
                )
            ],
            ("GET", f"/repos/{REPOSITORY}/git/trees/{feature_tree_sha}"): [
                _Response(
                    200,
                    {
                        "sha": feature_tree_sha,
                        "truncated": False,
                        "tree": [
                            {"path": "target.txt", "mode": "100644", "type": "blob", "sha": target_sha},
                            {"path": "sibling.txt", "mode": "100644", "type": "blob", "sha": sibling_sha},
                        ],
                    },
                )
            ],
            ("GET", f"/repos/{REPOSITORY}/git/trees/{unrelated_tree_sha}"): [
                _Response(200, {"sha": unrelated_tree_sha, "truncated": False, "tree": unrelated_entries})
            ],
            ("GET", f"/repos/{REPOSITORY}/git/blobs/{target_sha}"): [
                _Response(200, {"sha": target_sha, "encoding": "base64", "content": base64.b64encode(content).decode()})
            ],
            ("GET", f"/repos/{REPOSITORY}/git/blobs/{sibling_sha}"): [
                _Response(
                    200,
                    {"sha": sibling_sha, "encoding": "base64", "content": base64.b64encode(sibling_content).decode()},
                )
            ],
        }
    )

    manifest = load_trusted_base_manifest(
        fake,
        repository=REPOSITORY,
        base_sha=BASE_SHA,
        changed_paths=("src/feature/target.txt", "src/feature/sibling.txt"),
    )

    assert [entry.path for entry in manifest.entries] == [
        "src",
        "src/feature",
        "src/feature/sibling.txt",
        "src/feature/target.txt",
    ]
    assert manifest.old_text_for("src/feature/target.txt") == "old target\n"
    assert manifest.old_text_for("src/feature/sibling.txt") == "old sibling\n"
    assert [path for _method, path, _kwargs in fake.requests if "/git/trees/" in path] == [
        f"/repos/{REPOSITORY}/git/trees/{TREE_SHA}",
        f"/repos/{REPOSITORY}/git/trees/{source_tree_sha}",
        f"/repos/{REPOSITORY}/git/trees/{feature_tree_sha}",
    ]
    assert all(kwargs.get("params") is None for _method, _path, kwargs in fake.requests)


@pytest.mark.parametrize(
    "commit,tree",
    [
        ({"sha": "c" * 40, "tree": {"sha": TREE_SHA}}, {"sha": TREE_SHA, "truncated": False, "tree": []}),
        ({"sha": BASE_SHA, "tree": {"sha": TREE_SHA}}, {"sha": "c" * 40, "truncated": False, "tree": []}),
    ],
)
def test_manifest_rejects_mismatched_protected_commit_or_tree(
    commit: dict[str, object], tree: dict[str, object]
) -> None:
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/commits/{BASE_SHA}"): [_Response(200, commit)],
            ("GET", f"/repos/{REPOSITORY}/git/trees/{TREE_SHA}"): [_Response(200, tree)],
        }
    )

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(fake, repository=REPOSITORY, base_sha=BASE_SHA, changed_paths=())


def test_manifest_rejects_a_blob_that_does_not_match_its_git_object_sha() -> None:
    expected = b"expected\n"
    fake = _GitHubFake(_responses([_tree_entry("changed.txt", expected)], {_blob_sha(expected): b"substituted\n"}))

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(fake, repository=REPOSITORY, base_sha=BASE_SHA, changed_paths=("changed.txt",))


@pytest.mark.parametrize(
    "tree_payload",
    [
        {"sha": TREE_SHA, "truncated": True, "tree": []},
        {"sha": TREE_SHA, "truncated": False, "tree": [_tree_entry("a.txt", b"a"), _tree_entry("a.txt", b"b")]},
        {
            "sha": TREE_SHA,
            "truncated": False,
            "tree": [{"path": "../escape", "mode": "100644", "type": "blob", "sha": "c" * 40}],
        },
        {
            "sha": TREE_SHA,
            "truncated": False,
            "tree": [{"path": ".git/config", "mode": "100644", "type": "blob", "sha": "c" * 40}],
        },
    ],
)
def test_manifest_rejects_truncated_duplicate_or_noncanonical_tree_directory(tree_payload: dict[str, object]) -> None:
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/commits/{BASE_SHA}"): [
                _Response(200, {"sha": BASE_SHA, "tree": {"sha": TREE_SHA}})
            ],
            ("GET", f"/repos/{REPOSITORY}/git/trees/{TREE_SHA}"): [_Response(200, tree_payload)],
        }
    )

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(fake, repository=REPOSITORY, base_sha=BASE_SHA, changed_paths=())


def test_manifest_rejects_tree_over_the_entry_limit() -> None:
    entries = [_tree_entry("one.txt", b"one"), _tree_entry("two.txt", b"two")]
    fake = _GitHubFake(_responses(entries, {}))

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(
            fake,
            repository=REPOSITORY,
            base_sha=BASE_SHA,
            changed_paths=(),
            limits=PublicationBaseLimits(max_tree_entries=1),
        )


def test_manifest_rejects_tree_over_the_response_byte_limit() -> None:
    fake = _GitHubFake(_responses([], {}))

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(
            fake,
            repository=REPOSITORY,
            base_sha=BASE_SHA,
            changed_paths=(),
            limits=PublicationBaseLimits(max_tree_response_bytes=1),
        )


def test_manifest_rejects_tree_walk_over_the_aggregate_entry_limit() -> None:
    child_tree_sha = "c" * 40
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/commits/{BASE_SHA}"): [
                _Response(200, {"sha": BASE_SHA, "tree": {"sha": TREE_SHA}})
            ],
            ("GET", f"/repos/{REPOSITORY}/git/trees/{TREE_SHA}"): [
                _Response(
                    200,
                    {
                        "sha": TREE_SHA,
                        "truncated": False,
                        "tree": [{"path": "dir", "mode": "040000", "type": "tree", "sha": child_tree_sha}],
                    },
                )
            ],
            ("GET", f"/repos/{REPOSITORY}/git/trees/{child_tree_sha}"): [
                _Response(
                    200,
                    {
                        "sha": child_tree_sha,
                        "truncated": False,
                        "tree": [_tree_entry("target.txt", b"target")],
                    },
                )
            ],
        }
    )

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(
            fake,
            repository=REPOSITORY,
            base_sha=BASE_SHA,
            changed_paths=("dir/target.txt",),
            limits=PublicationBaseLimits(max_total_tree_entries=1),
        )


def test_manifest_rejects_tree_walk_over_the_aggregate_response_byte_limit() -> None:
    child_tree_sha = "c" * 40
    root_tree = {
        "sha": TREE_SHA,
        "truncated": False,
        "tree": [{"path": "dir", "mode": "040000", "type": "tree", "sha": child_tree_sha}],
    }
    child_tree = {
        "sha": child_tree_sha,
        "truncated": False,
        "tree": [_tree_entry("target.txt", b"target")],
    }
    aggregate_limit = (
        len(json.dumps(root_tree, ensure_ascii=False, separators=(",", ":")).encode())
        + len(json.dumps(child_tree, ensure_ascii=False, separators=(",", ":")).encode())
        - 1
    )
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/commits/{BASE_SHA}"): [
                _Response(200, {"sha": BASE_SHA, "tree": {"sha": TREE_SHA}})
            ],
            ("GET", f"/repos/{REPOSITORY}/git/trees/{TREE_SHA}"): [_Response(200, root_tree)],
            ("GET", f"/repos/{REPOSITORY}/git/trees/{child_tree_sha}"): [_Response(200, child_tree)],
        }
    )

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(
            fake,
            repository=REPOSITORY,
            base_sha=BASE_SHA,
            changed_paths=("dir/target.txt",),
            limits=PublicationBaseLimits(max_total_tree_response_bytes=aggregate_limit),
        )


def test_manifest_rejects_tree_path_over_the_path_byte_limit() -> None:
    fake = _GitHubFake(_responses([_tree_entry("long-name.txt", b"x")], {}))

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(
            fake,
            repository=REPOSITORY,
            base_sha=BASE_SHA,
            changed_paths=(),
            limits=PublicationBaseLimits(max_path_bytes=5),
        )


@pytest.mark.parametrize(
    "mode,entry_type",
    [("120000", "blob"), ("160000", "commit"), ("040000", "tree")],
)
def test_manifest_rejects_special_changed_targets(mode: str, entry_type: str) -> None:
    content = b"target"
    fake = _GitHubFake(_responses([_tree_entry("target", content, mode=mode, entry_type=entry_type)], {}))

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(fake, repository=REPOSITORY, base_sha=BASE_SHA, changed_paths=("target",))


def test_manifest_rejects_an_added_path_below_a_base_symlink_or_submodule() -> None:
    symlink = _tree_entry("linked", b"target", mode="120000")
    submodule = {"path": "module", "mode": "160000", "type": "commit", "sha": "c" * 40}
    fake = _GitHubFake(_responses([symlink, submodule], {}))

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(
            fake,
            repository=REPOSITORY,
            base_sha=BASE_SHA,
            changed_paths=("linked/new.txt", "module/new.txt"),
        )


@pytest.mark.parametrize("content", [b"contains\0nul", b"\xff\xfe"])
def test_manifest_rejects_binary_or_non_utf8_changed_blob(content: bytes) -> None:
    fake = _GitHubFake(_responses([_tree_entry("target.txt", content)], {_blob_sha(content): content}))

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(fake, repository=REPOSITORY, base_sha=BASE_SHA, changed_paths=("target.txt",))


@pytest.mark.parametrize(
    "changed_path", ["../escape", "/absolute", "dir//file", "node_modules/pkg.js", "build/output.js"]
)
def test_manifest_rejects_untrusted_changed_paths_before_request(changed_path: str) -> None:
    fake = _GitHubFake({})

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(fake, repository=REPOSITORY, base_sha=BASE_SHA, changed_paths=(changed_path,))

    assert fake.requests == []


def test_manifest_rejects_duplicate_changed_paths() -> None:
    fake = _GitHubFake({})

    with pytest.raises(PublicationBaseError):
        load_trusted_base_manifest(
            fake, repository=REPOSITORY, base_sha=BASE_SHA, changed_paths=("same.txt", "same.txt")
        )

    assert fake.requests == []


@pytest.mark.parametrize("error", [GitHubRateLimitError("limited", retry_after=60), requests.RequestException("down")])
def test_manifest_propagates_read_only_rate_and_transport_errors(error: Exception) -> None:
    fake = _GitHubFake({("GET", f"/repos/{REPOSITORY}/git/commits/{BASE_SHA}"): [error]})

    with pytest.raises(type(error)):
        load_trusted_base_manifest(fake, repository=REPOSITORY, base_sha=BASE_SHA, changed_paths=())
