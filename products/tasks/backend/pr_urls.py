def read_pr_urls(output: object) -> list[str]:
    if not isinstance(output, dict):
        return []

    raw_urls = output.get("pr_urls")
    urls: list[object] = raw_urls if isinstance(raw_urls, list) else []
    pr_url = output.get("pr_url")
    candidates = [*urls, pr_url]
    return list(dict.fromkeys(url for url in candidates if isinstance(url, str) and url))


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
