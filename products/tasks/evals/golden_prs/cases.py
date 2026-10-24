import re
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

GOLDEN_SET_PATH = Path(__file__).with_name("golden_prs.json")

HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
TEMPLATE_FOOTER = re.compile(r"^.*Stay up-to-date with \[PostHog coding conventions\].*$", re.MULTILINE)
BLANK_RUN = re.compile(r"\n{3,}")


@dataclass(frozen=True, kw_only=True, slots=True)
class GoldenPR:
    number: int
    author: str
    title: str
    body: str
    merged_at: str
    merge_commit_sha: str

    @property
    def parent_sha(self) -> str:
        return f"{self.merge_commit_sha}^"


def load_golden_prs(path: Path = GOLDEN_SET_PATH) -> list[GoldenPR]:
    return [GoldenPR(**entry) for entry in json.loads(path.read_text())]


def select_golden_prs(prs: Iterable[GoldenPR], numbers: Iterable[int]) -> list[GoldenPR]:
    # A one-shot iterator would otherwise be consumed by the unknown-number check below, leaving
    # nothing for the return comprehension to read.
    numbers = list(numbers)
    by_number = {pr.number: pr for pr in prs}
    unknown = sorted(set(numbers) - by_number.keys())
    if unknown:
        raise ValueError(f"Not in the golden set: {unknown}")
    return [by_number[number] for number in numbers]


def clean_description(body: str) -> str:
    without_comments = HTML_COMMENT.sub("", body.replace("\r", ""))
    without_footer = TEMPLATE_FOOTER.sub("", without_comments)
    return BLANK_RUN.sub("\n\n", without_footer).strip()


def build_prompt(pr: GoldenPR) -> str:
    return (
        "You are working in a checkout of the PostHog repository. "
        "Implement the change described below by editing files in the working directory. "
        "Do not commit. Stop when the change is complete.\n\n"
        f"# {pr.title}\n\n{clean_description(pr.body)}\n"
    )
