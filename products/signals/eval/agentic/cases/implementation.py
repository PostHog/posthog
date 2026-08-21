from __future__ import annotations

from products.signals.eval.agentic.datasets import ImplementationCase, ImplementationExpectation

_REPOSITORY = "posthog/hedgebox"


def _case(
    case_id: str,
    issue_prompt: str,
    expected_files: tuple[str, ...],
    expected_keywords: tuple[str, ...],
    *,
    forbidden: tuple[str, ...] = ("pnpm-lock.yaml",),
    max_files: int = 2,
) -> ImplementationCase:
    return ImplementationCase(
        case_id=case_id,
        step="implementation",
        repo=_REPOSITORY,
        issue_prompt=issue_prompt,
        expected=ImplementationExpectation(
            expected_file_substrings=expected_files,
            forbidden_file_substrings=forbidden,
            expected_diff_keywords=expected_keywords,
            min_files_changed=1,
            max_files_changed=max_files,
        ),
    )


CASES: list[ImplementationCase] = [
    _case(
        "impl_hedgebox_clamp",
        "In `src/lib/utils.ts`, add and export `clamp(value: number, minimum: number, maximum: number): number`. "
        "Return value bounded to the inclusive minimum and maximum.",
        ("src/lib/utils.ts",),
        ("clamp", "minimum", "maximum"),
    ),
    _case(
        "impl_hedgebox_truncate",
        "In `src/lib/utils.ts`, add and export `truncate(value: string, maxLength: number): string`. Return the "
        "input unchanged when it fits; otherwise return the first maxLength characters followed by `...`.",
        ("src/lib/utils.ts",),
        ("truncate", "maxLength", "..."),
    ),
    _case(
        "impl_hedgebox_valid_email",
        "In `src/lib/utils.ts`, add and export `isValidEmail(value: string): boolean` using a regular expression.",
        ("src/lib/utils.ts",),
        ("isValidEmail", "boolean"),
    ),
    _case(
        "impl_hedgebox_file_size_negative",
        "Update `formatFileSize` in `src/lib/utils.ts` so negative byte counts return `0 Bytes` instead of "
        "producing an invalid logarithm result. Preserve existing behavior for positive values.",
        ("src/lib/utils.ts",),
        ("formatFileSize", "bytes <= 0", "0 Bytes"),
    ),
    _case(
        "impl_hedgebox_json_icon",
        "Update `getFileIcon` in `src/lib/utils.ts` so JSON MIME types and filenames use the 🧩 icon. Keep all "
        "existing icon mappings unchanged.",
        ("src/lib/utils.ts",),
        ("json", "🧩"),
    ),
    _case(
        "impl_hedgebox_find_file",
        "In `src/lib/data.ts`, add and export `findFileById(id: string): HedgeboxFile | undefined`, returning "
        "the matching item from `sampleFiles`.",
        ("src/lib/data.ts",),
        ("findFileById", "sampleFiles.find"),
    ),
    _case(
        "impl_hedgebox_storage_percent",
        "In `src/lib/data.ts`, add and export `storageUsagePercent(account: HedgeboxAccount): number`. Return the "
        "used-storage percentage, or zero when maxStorage is zero.",
        ("src/lib/data.ts",),
        ("storageUsagePercent", "usedStorage", "maxStorage"),
    ),
    _case(
        "impl_hedgebox_sort_files",
        "In `src/lib/data.ts`, add and export `sortFilesNewestFirst(files: HedgeboxFile[]): HedgeboxFile[]`. "
        "Return a new array sorted by uploadedAt descending without mutating the input.",
        ("src/lib/data.ts",),
        ("sortFilesNewestFirst", "uploadedAt", "sort"),
    ),
    _case(
        "impl_hedgebox_auth_redirect",
        "Update `useAuthRedirect` in `src/lib/hooks.ts` to accept an optional `destination` string defaulting to "
        "`/login`, and redirect unauthenticated users to that destination.",
        ("src/lib/hooks.ts",),
        ("destination", "/login", "router.push"),
    ),
    _case(
        "impl_hedgebox_header_nav_label",
        "Add an accessible `aria-label` of `Main navigation` to the desktop navigation container in "
        "`src/components/Header.tsx`. Keep the change limited to that component.",
        ("src/components/Header.tsx",),
        ("aria-label", "Main navigation"),
        max_files=1,
    ),
]
