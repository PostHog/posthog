"""The contract every provider importer implements.

A provider importer knows one messaging tool: how to store and check its credentials, and how to page through each
kind of data it can import. It knows nothing about Temporal or run state. `runs.py` drives the steps, saves progress
after each page, and resumes a retried step from the last saved checkpoint.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import ClassVar

from posthog.dataclasses import frozen

# Where a step continues after a page. Each step defines its own keys. The values are JSON-safe because the
# checkpoint is stored in the run's `progress`.
StepCheckpoint = dict[str, str | int]


class ImportCredentialsMissing(Exception):
    """The request has no API key and none is stored. The message names what is missing."""


class ImportCredentialsConflict(Exception):
    """A key is stored and the request sends another one. The message tells the caller to delete it first."""


class ImportCredentialsInvalid(Exception):
    """The provider rejected the API key. A retry does not fix this."""


class UnknownImportStep(Exception):
    """The provider has no step with this key."""


@frozen
class ImportStepSpec:
    key: str
    label: str
    description: str


@frozen
class ImportContext:
    team_id: int
    created_by_id: int | None
    integration_id: int | None


@frozen
class ImportPage:
    # How many source records the page read.
    processed: int
    # How many records the page added in PostHog. Records that already exist do not count.
    imported: int
    # Problems with single records that do not fail the step.
    warnings: tuple[str, ...] = ()
    # Where to continue when the step runs again after this page. None when the step has no more pages.
    checkpoint: StepCheckpoint | None = None


class ImportProvider(ABC):
    key: ClassVar[str]
    label: ClassVar[str]
    # The steps in the order they run. Each one is safe to run again over records it already imported.
    steps: ClassVar[tuple[ImportStepSpec, ...]]

    @abstractmethod
    def save_credentials(self, team_id: int, api_key: str | None, created_by_id: int | None) -> int:
        """Check the API key with the provider, store it on first use, and return the integration id.

        Without `api_key`, use the stored key. Raises the ImportCredentials* errors.
        """

    @abstractmethod
    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        """Import one step from `checkpoint`, or from the start when it is None, and yield each page after it is saved."""
