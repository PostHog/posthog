#!/usr/bin/env python3

import logging
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)


# Pydantic models matching the chunking schema
class FileInfo(BaseModel):
    filename: str = Field(description="Path to the file")


class Chunk(BaseModel):
    chunk_id: int = Field(description="Unique identifier for the chunk, ordered by review priority")
    files: list[FileInfo] = Field(description="List of files that belong to this chunk", min_length=1)
    chunk_type: (
        Literal[
            "infrastructure",
            "data_model",
            "business_logic",
            "api",
            "frontend",
            "tests",
            "documentation",
            "configuration",
            "refactoring",
            "feature",
            "bugfix",
        ]
        | None
    ) = Field(None, description="Type of changes in this chunk")
    key_changes: list[str] | None = Field(
        default_factory=lambda: [],
        description="Bullet points highlighting the most important changes",
    )
    model_config = {"populate_by_name": True}


class ChunksList(BaseModel):
    chunks: list[Chunk] = Field(description="List of chunks")
