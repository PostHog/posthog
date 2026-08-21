from __future__ import annotations

from products.signals.evals.agentic.datasets import ImplementationCase

_REPOSITORY = "posthog/hedgebox"


def _case(
    case_id: str,
    issue_prompt: str,
) -> ImplementationCase:
    return ImplementationCase(
        case_id=case_id,
        step="implementation",
        repo=_REPOSITORY,
        issue_prompt=issue_prompt,
    )


CASES: list[ImplementationCase] = [
    _case(
        "impl_hedgebox_clamp",
        "In `src/lib/utils.ts`, add and export `clamp(value: number, minimum: number, maximum: number): number`. "
        "Return value bounded to the inclusive minimum and maximum.",
    ),
    _case(
        "impl_hedgebox_truncate",
        "In `src/lib/utils.ts`, add and export `truncate(value: string, maxLength: number): string`. Return the "
        "input unchanged when it fits; otherwise return the first maxLength characters followed by `...`.",
    ),
    _case(
        "impl_hedgebox_valid_email",
        "In `src/lib/utils.ts`, add and export `isValidEmail(value: string): boolean` using a regular expression.",
    ),
    _case(
        "impl_hedgebox_file_size_negative",
        "Update `formatFileSize` in `src/lib/utils.ts` so negative byte counts return `0 Bytes` instead of "
        "producing an invalid logarithm result. Preserve existing behavior for positive values.",
    ),
    _case(
        "impl_hedgebox_json_icon",
        "Update `getFileIcon` in `src/lib/utils.ts` so JSON MIME types and filenames use the 🧩 icon. Keep all "
        "existing icon mappings unchanged.",
    ),
    _case(
        "impl_hedgebox_find_file",
        "In `src/lib/data.ts`, add and export `findFileById(id: string): HedgeboxFile | undefined`, returning "
        "the matching item from `sampleFiles`.",
    ),
    _case(
        "impl_hedgebox_storage_percent",
        "In `src/lib/data.ts`, add and export `storageUsagePercent(account: HedgeboxAccount): number`. Return the "
        "used-storage percentage, or zero when maxStorage is zero.",
    ),
    _case(
        "impl_hedgebox_sort_files",
        "In `src/lib/data.ts`, add and export `sortFilesNewestFirst(files: HedgeboxFile[]): HedgeboxFile[]`. "
        "Return a new array sorted by uploadedAt descending without mutating the input.",
    ),
    _case(
        "impl_hedgebox_auth_redirect",
        "Update `useAuthRedirect` in `src/lib/hooks.ts` to accept an optional `destination` string defaulting to "
        "`/login`, and redirect unauthenticated users to that destination.",
    ),
    _case(
        "impl_hedgebox_header_nav_label",
        "Add an accessible `aria-label` of `Main navigation` to the desktop navigation container in "
        "`src/components/Header.tsx`. Keep the change limited to that component.",
    ),
]
