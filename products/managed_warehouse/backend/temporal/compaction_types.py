from pydantic import BaseModel


class DucklakeCompactionInput(BaseModel):
    """Input for the DuckLake compaction workflow."""

    # Target file size for compaction (default: 512MB)
    target_file_size: str = "512MB"
    # Tables to compact (if empty, compacts all tables)
    tables: list[str] = []
    # Whether to run in dry-run mode (no actual compaction)
    dry_run: bool = False
    # Organization whose DuckLake catalog connection should be used. None only in dev
    # mode, where get_org_config() falls back to the local env-var config regardless.
    organization_id: str | None = None
