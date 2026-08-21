from __future__ import annotations

from products.signals.evals.agentic.datasets import ImplementationCase

_REPOSITORY = "posthog/hedgebox"


def _case(
    case_id: str,
    issue_prompt: str,
    judging_notes: str = "",
) -> ImplementationCase:
    return ImplementationCase(
        case_id=case_id,
        step="implementation",
        repo=_REPOSITORY,
        issue_prompt=issue_prompt,
        judging_notes=judging_notes,
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
    _case(
        "impl_hedgebox_download_flow",
        "Customers report that Download records analytics but never starts a browser download. Fix downloads from "
        "both the files list and file details page. Use the `/api/files/{id}/download` endpoint, keep the behavior in "
        "one shared helper, and record `downloaded_file` only after the download has been initiated.",
        "A strong fix discovers both download handlers, centralizes the browser side effect, preserves file metadata "
        "in analytics, and does not leave the details button stuck in its processing state.",
    ),
    _case(
        "impl_hedgebox_auth_return_path",
        "Unauthenticated users who open a file link are sent to login and then lose the file they intended to view. "
        "Preserve the requested path through login and return there after authentication. Accept only internal paths "
        "beginning with `/`; reject protocol-relative and absolute URLs, and keep `/files` as the fallback.",
        "The hook and login page should cooperate on a URL-encoded return path without introducing an open redirect. "
        "Loading and already-authenticated behavior should remain stable.",
    ),
    _case(
        "impl_hedgebox_bulk_delete",
        "Bulk delete currently removes selected files immediately and updates state once per file. Ask for one "
        "confirmation naming the number selected, make no changes when cancelled, then delete the confirmed files in "
        "one state update, clear the selection, and emit one `deleted_file` event for each removed file.",
        "The implementation should use the current selected files as one snapshot, avoid calling the single-file state "
        "handler in a loop, and preserve single-file deletion behavior.",
    ),
    _case(
        "impl_hedgebox_share_feedback",
        "The Share modal reports a copied link even when the Clipboard API rejects. Make copying asynchronous, show a "
        "clear success or failure message in the modal, and emit `copied_share_link` only after a successful write. "
        "Reset stale feedback whenever the modal is reopened.",
        "A strong fix handles the clipboard promise without an unhandled rejection, exposes accessible feedback, keeps "
        "the existing share link, and does not count failed copies as successful analytics.",
    ),
]
