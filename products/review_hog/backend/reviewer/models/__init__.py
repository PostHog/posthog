import json
from pathlib import Path

from products.review_hog.backend.reviewer.models.issue_deduplicator import IssueDeduplication
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import IssuesReview
from products.review_hog.backend.reviewer.models.perspective_selection import PerspectiveSelection
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def generate_issues_review_schema() -> None:
    schema_path = PROMPTS_DIR / "issues_review" / "schema.json"
    with schema_path.open("w") as f:
        f.write(json.dumps(IssuesReview.model_json_schema(), indent=2))


def generate_chunking_schema() -> None:
    schema_path = PROMPTS_DIR / "chunking" / "schema.json"
    with schema_path.open("w") as f:
        f.write(json.dumps(ChunksList.model_json_schema(), indent=2))


def generate_issue_validation_schema() -> None:
    schema_path = PROMPTS_DIR / "issue_validation" / "schema.json"
    with schema_path.open("w") as f:
        f.write(json.dumps(IssueValidation.model_json_schema(), indent=2))


def generate_issue_deduplicator_schema() -> None:
    schema_path = PROMPTS_DIR / "issue_deduplicator" / "schema.json"
    with schema_path.open("w") as f:
        f.write(json.dumps(IssueDeduplication.model_json_schema(), indent=2))


def generate_perspective_selection_schema() -> None:
    schema_path = PROMPTS_DIR / "perspective_selection" / "schema.json"
    with schema_path.open("w") as f:
        f.write(json.dumps(PerspectiveSelection.model_json_schema(), indent=2))


def generate_all_schemas() -> None:
    generate_issues_review_schema()
    generate_chunking_schema()
    generate_issue_validation_schema()
    generate_issue_deduplicator_schema()
    generate_perspective_selection_schema()
