import re

from products.wizard.backend.facade.errors import InvalidBranchError, InvalidRepositoryError

GIT_BRANCH_NAME_MAX_LENGTH = 255
# Stricter than git's ref name rules: it admits only the characters that branch names use in practice.
_GIT_BRANCH_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")


def validate_git_repository_name(repository: str) -> None:
    owner, separator, name = repository.partition("/")

    if not separator or not owner or not name or "/" in name:
        raise InvalidRepositoryError


def validate_git_branch_name(branch: str) -> None:
    if (
        not branch
        or len(branch) > GIT_BRANCH_NAME_MAX_LENGTH
        or _GIT_BRANCH_NAME_PATTERN.fullmatch(branch) is None
        or branch.startswith(("-", "/", "."))
        or branch.endswith(("/", ".", ".lock"))
        or ".." in branch
        or "//" in branch
        or "/." in branch
    ):
        raise InvalidBranchError
