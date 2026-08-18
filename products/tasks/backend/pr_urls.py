from collections.abc import Iterable


def read_pr_urls(output: object) -> list[str]:
    if not isinstance(output, dict):
        return []

    raw_urls = output.get("pr_urls")
    urls: list[object] = raw_urls if isinstance(raw_urls, list) else []
    pr_url = output.get("pr_url")
    candidates = [*urls, pr_url]
    return list(dict.fromkeys(url for url in candidates if isinstance(url, str) and url))


def read_agent_opened_pr_urls(output: object) -> list[str]:
    """PR URLs this run's agent is attested to have opened itself.

    Only the caller-facing run APIs (the sandbox agent reporting its own PR) and the
    SHA-verified webhook backstop write this set. A bare branch-name webhook match never
    does. Membership therefore means we opened the PR, not that a PR shares the branch.
    """
    if not isinstance(output, dict):
        return []
    raw = output.get("agent_opened_pr_urls")
    urls: list[object] = raw if isinstance(raw, list) else []
    return list(dict.fromkeys(url for url in urls if isinstance(url, str) and url))


def read_pushed_commit_shas(output: object) -> set[str]:
    """SHAs of commits the run pushed, from the latest signed-commit report."""
    if not isinstance(output, dict) or not isinstance(output.get("commit_push"), dict):
        return set()
    commits = output["commit_push"].get("commits")
    if not isinstance(commits, list):
        return set()
    return {c["sha"] for c in commits if isinstance(c, dict) and isinstance(c.get("sha"), str) and c["sha"]}


def with_agent_opened_pr_urls(output: dict, urls: Iterable[str]) -> dict:
    """Return ``output`` with ``urls`` added to the agent-opened set, or unchanged when nothing is new."""
    existing = read_agent_opened_pr_urls(output)
    merged = list(dict.fromkeys([*existing, *(url for url in urls if isinstance(url, str) and url)]))
    if merged == existing:
        return output
    return {**output, "agent_opened_pr_urls": merged}


def read_head_branches(output: object) -> list[dict[str, str]]:
    if not isinstance(output, dict):
        return []

    raw_branches = output.get("head_branches")
    branches: list[object] = raw_branches if isinstance(raw_branches, list) else []
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in branches:
        if not isinstance(candidate, dict):
            continue
        repository = candidate.get("repository")
        branch = candidate.get("branch")
        if not isinstance(repository, str) or not repository or not isinstance(branch, str) or not branch:
            continue
        pair = (repository.strip().lower(), branch)
        if pair in seen:
            continue
        seen.add(pair)
        normalized.append({"repository": pair[0], "branch": pair[1]})
    return normalized


def merge_pr_output(existing: object, incoming: dict) -> dict:
    current = existing if isinstance(existing, dict) else {}
    merged = {**current, **incoming}
    head_branches = [*read_head_branches(incoming), *read_head_branches(current)]
    if head_branches:
        merged["head_branches"] = read_head_branches({"head_branches": head_branches})
    urls = list(dict.fromkeys([*read_pr_urls(incoming), *read_pr_urls(current)]))
    if not urls:
        return merged

    primary = incoming.get("pr_url") or current.get("pr_url") or urls[0]
    ordered = [primary, *(url for url in urls if url != primary)]
    return {**merged, "pr_url": primary, "pr_urls": ordered}
