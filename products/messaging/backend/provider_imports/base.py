"""The contract every provider importer implements.

A provider importer knows one messaging tool: how to check and store its credentials, and how to page through each
kind of data it can import. It knows nothing about Temporal or run state. `runs.py` drives the steps, saves each page
together with the step's progress, and resumes a retried step from the last saved checkpoint.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import field
from typing import ClassVar

from posthog.dataclasses import frozen

# Where a step continues after a page. Each step defines its own keys. The values are JSON-safe because the
# checkpoint is stored in the run's `progress`.
StepCheckpoint = dict[str, str | int]


class ImportStepError(Exception):
    """A failure whose message is safe to show the user. The run shows a generic message for any other exception."""


class ImportCredentialsMissing(ImportStepError):
    """The request has no API key and none is stored. The message names what is missing."""


class ImportCredentialsConflict(ImportStepError):
    """A key is stored and the request sends another one. The message tells the caller to delete it first."""


class ImportCredentialsInvalid(ImportStepError):
    """The provider rejected the API key. A retry does not fix this."""


class ImportProviderUnavailable(ImportStepError):
    """The provider did not respond or returned a server error. A later retry can succeed."""


class UnknownImportStep(ImportStepError):
    """The provider has no step with this key."""


@frozen
class ImportStepSpec:
    key: str
    label: str
    description: str


@frozen
class ImportCredentials:
    api_key: str = field(repr=False)


@frozen
class ImportContext:
    team_id: int
    created_by_id: int | None
    integration_id: int | None


@frozen
class SavedPage:
    # How many records the page added or changed in PostHog. Records that already match do not count.
    imported: int
    # Problems with single records that do not fail the step.
    warnings: tuple[str, ...] = ()


@frozen
class ImportPage:
    # How many source records the page read.
    processed: int
    # Writes the page to PostHog. The runner calls it in the transaction that saves the step's progress, so the page
    # and its counts and checkpoint commit together.
    save: Callable[[], SavedPage]
    # Where to continue when the step runs again after this page. None on the last page of the step.
    checkpoint: StepCheckpoint | None = None


class ImportProvider(ABC):
    key: ClassVar[str]
    label: ClassVar[str]
    # The steps in the order they run. Each one is safe to run again over records it already imported.
    steps: ClassVar[tuple[ImportStepSpec, ...]]

    @abstractmethod
    def check_credentials(self, team_id: int, api_key: str | None) -> ImportCredentials:
        """Choose the API key to import with and check it with the provider. Without `api_key`, use the stored key.

        This runs before the import claims its run, so it must not store anything. Raises the ImportCredentials*
        errors, or ImportProviderUnavailable when the provider can't answer.
        """

    @abstractmethod
    def store_credentials(self, team_id: int, credentials: ImportCredentials, created_by_id: int | None) -> int:
        """Store checked credentials on first use and return the integration id.

        This runs in the transaction that claims the run, so a request that loses the claim stores nothing.
        """

    @abstractmethod
    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        """Fetch one step's pages from `checkpoint`, or from the start when it is None, without saving them."""
