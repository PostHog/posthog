import ast


def extract_target_names(target: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, ast.Tuple | ast.List):
        for item in target.elts:
            names.update(extract_target_names(item))
    elif isinstance(target, ast.Starred):
        names.update(extract_target_names(target.value))
    return names


def collect_arg_names(arguments: ast.arguments) -> set[str]:
    names = {arg.arg for arg in arguments.args}
    names.update({arg.arg for arg in arguments.posonlyargs})
    names.update({arg.arg for arg in arguments.kwonlyargs})
    if arguments.vararg:
        names.add(arguments.vararg.arg)
    if arguments.kwarg:
        names.add(arguments.kwarg.arg)
    return names


def match_capture_names(pattern: ast.pattern) -> set[str]:
    """Names a match-case pattern binds — captures are locals, not external frames."""
    names: set[str] = set()
    if isinstance(pattern, ast.MatchAs):
        if pattern.name is not None:
            names.add(pattern.name)
    elif isinstance(pattern, ast.MatchStar):
        if pattern.name is not None:
            names.add(pattern.name)
    elif isinstance(pattern, ast.MatchMapping):
        if pattern.rest is not None:
            names.add(pattern.rest)
    for sub in _sub_patterns(pattern):
        names |= match_capture_names(sub)
    return names


def _sub_patterns(pattern: ast.pattern) -> list[ast.pattern]:
    if isinstance(pattern, ast.MatchAs):
        return [pattern.pattern] if pattern.pattern is not None else []
    if isinstance(pattern, ast.MatchMapping | ast.MatchSequence | ast.MatchOr):
        return pattern.patterns
    if isinstance(pattern, ast.MatchClass):
        return [*pattern.patterns, *pattern.kwd_patterns]
    return []


def dotted_name(value: ast.AST) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        base = dotted_name(value.value)
        if base:
            return f"{base}.{value.attr}"
        return value.attr
    return None
