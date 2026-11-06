"""The contract every provider importer implements.

A provider importer knows one messaging tool: how to check and store its credentials, and how to page through each
kind of data it can import. It knows nothing about Temporal or run state. `runs.py` drives the steps, saves each page
together with the step's progress, and resumes a retried step from the last saved checkpoint.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping
from dataclasses import field
from typing import ClassVar, Literal

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
    # What the step counts in its summary, as (key, label) pairs in display order.
    count_labels: tuple[tuple[str, str], ...] = ()


@frozen
class ImportCredentials:
    api_key: str = field(repr=False)


@frozen
class ImportContext:
    team_id: int
    created_by_id: int | None
    integration_id: int | None
    # The key a provider with `retains_credentials = False` reads for this run only.
    api_key: str | None = field(default=None, repr=False)


ImportItemStatus = Literal["created", "skipped", "failed", "listed"]


@frozen
class ImportItem:
    """One object the step handled, such as a template, that the person running the import may need to act on."""

    label: str
    status: ImportItemStatus
    # A path in the app, for example the draft the step created.
    url: str | None = None
    notes: tuple[str, ...] = ()


@frozen
class SavedPage:
    # How many records the page added or changed in PostHog. Records that already match do not count.
    imported: int
    # Problems with single records that do not fail the step.
    warnings: tuple[str, ...] = ()
    # Added to the step's totals, by the keys in the step's `count_labels`.
    counts: Mapping[str, int] = field(default_factory=dict)
    items: tuple[ImportItem, ...] = ()


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
    # A provider whose key can do more than read keeps it only on the run, which clears it when it ends.
    retains_credentials: ClassVar[bool] = True
    # A new run continues each failed step of the run before it, when a step's checkpoint stays valid between runs.
    resumes_after_failure: ClassVar[bool] = False
    # Hides the provider unless this flag is on for the team.
    feature_flag: ClassVar[str | None] = None
    api_key_label: ClassVar[str] = "API key"
    api_key_help: ClassVar[str] = ""
    api_key_url: ClassVar[str | None] = None
    # What the import can't bring over, shown before it starts.
    not_imported: ClassVar[str] = ""
    # What the person does once the import has finished, in order.
    next_steps: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def check_credentials(self, team_id: int, api_key: str | None) -> ImportCredentials:
        """Choose the API key to import with and check it with the provider. Without `api_key`, use the stored key.

        This runs before the import claims its run, so it must not store anything. Raises the ImportCredentials*
        errors, or ImportProviderUnavailable when the provider can't answer.
        """

    def store_credentials(self, team_id: int, credentials: ImportCredentials, created_by_id: int | None) -> int | None:
        """Store checked credentials on first use and return the integration id.

        This runs in the transaction that claims the run, so a request that loses the claim stores nothing. It does
        not run for a provider with `retains_credentials = False`.
        """
        raise NotImplementedError(f"{self.key} keeps its credentials on the run.")

    @abstractmethod
    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        """Fetch one step's pages from `checkpoint`, or from the start when it is None, without saving them."""
