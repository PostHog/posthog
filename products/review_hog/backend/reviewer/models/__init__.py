import json
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def generate_chunk_analysis_schema() -> None:
    from reviewer.models.chunk_analysis import ChunkAnalysis

    schema_path = PROMPTS_DIR / "chunk_analysis" / "schema.json"
    with schema_path.open("w") as f:
        f.write(json.dumps(ChunkAnalysis.model_json_schema(), indent=2))


def generate_issues_review_schema() -> None:
    from reviewer.models.issues_review import IssuesReview

    schema_path = PROMPTS_DIR / "issues_review" / "schema.json"
    with schema_path.open("w") as f:
        f.write(json.dumps(IssuesReview.model_json_schema(), indent=2))


def generate_chunking_schema() -> None:
    from reviewer.models.split_pr_into_chunks import ChunksList

    schema_path = PROMPTS_DIR / "chunking" / "schema.json"
    with schema_path.open("w") as f:
        f.write(json.dumps(ChunksList.model_json_schema(), indent=2))


def generate_issue_validation_schema() -> None:
    from reviewer.models.issue_validation import IssueValidation

    schema_path = PROMPTS_DIR / "issue_validation" / "schema.json"
    with schema_path.open("w") as f:
        f.write(json.dumps(IssueValidation.model_json_schema(), indent=2))


def generate_issue_deduplicator_schema() -> None:
    from reviewer.models.issue_deduplicator import IssueDeduplication

    schema_path = PROMPTS_DIR / "issue_deduplicator" / "schema.json"
    with schema_path.open("w") as f:
        f.write(json.dumps(IssueDeduplication.model_json_schema(), indent=2))


def generate_all_schemas() -> None:
    generate_chunk_analysis_schema()
    generate_issues_review_schema()
    generate_chunking_schema()
    generate_issue_validation_schema()
    generate_issue_deduplicator_schema()
