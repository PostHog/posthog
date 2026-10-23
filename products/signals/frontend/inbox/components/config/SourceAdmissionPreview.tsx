import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import {
    SourceAdmissionFiltersModalLogicProps,
    sourceAdmissionFiltersModalLogic,
} from '../../logics/sourceAdmissionFiltersModalLogic'

export function SourceAdmissionPreview({
    logicProps,
}: {
    logicProps: SourceAdmissionFiltersModalLogicProps
}): JSX.Element {
    const { preview, previewLoading, previewError } = useValues(sourceAdmissionFiltersModalLogic(logicProps))
    const { loadPreview } = useActions(sourceAdmissionFiltersModalLogic(logicProps))

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-semibold">Preview</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={loadPreview}
                    loading={previewLoading}
                    data-attr="signal-source-admission-filters-preview"
                >
                    Preview matches
                </LemonButton>
            </div>
            {previewLoading ? (
                <LemonSkeleton className="h-16 w-full" />
            ) : previewError ? (
                <LemonBanner type="error">{previewError}</LemonBanner>
            ) : preview === null ? (
                <span className="text-xs text-secondary">
                    See which recently synced issues match these filters. A preview makes no AI calls and doesn't change
                    your inbox.
                </span>
            ) : preview.tables_checked === 0 ? (
                <span className="text-xs text-secondary">There are no synced issues to preview yet.</span>
            ) : preview.issues.length === 0 ? (
                <span className="text-xs text-secondary">
                    No issues from the last {preview.lookback_days} days match. With these filters, nothing synced
                    recently would be read.
                </span>
            ) : (
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-secondary">
                        {preview.truncated
                            ? `The ${preview.limit} most recent matches from the last ${preview.lookback_days} days. More issues match.`
                            : `${preview.issues.length} ${preview.issues.length === 1 ? 'issue' : 'issues'} from the last ${preview.lookback_days} days match.`}
                    </span>
                    <ul className="m-0 flex max-h-60 list-none flex-col gap-1 overflow-y-auto p-0">
                        {preview.issues.map((issue, index) => (
                            <li
                                key={`${issue.url ?? issue.title}-${index}`}
                                className="flex items-center gap-2 text-xs"
                            >
                                <span className="min-w-0 flex-1 truncate">
                                    {issue.url ? (
                                        <Link to={issue.url} target="_blank">
                                            {issue.title || 'Untitled issue'}
                                        </Link>
                                    ) : (
                                        issue.title || 'Untitled issue'
                                    )}
                                </span>
                                {issue.created_at && (
                                    <TZLabel time={issue.created_at} className="shrink-0 text-muted" />
                                )}
                            </li>
                        ))}
                    </ul>
                    {preview.tables_skipped > 0 && (
                        <span className="text-xs text-secondary">
                            The preview read {preview.tables_checked} of{' '}
                            {preview.tables_checked + preview.tables_skipped} synced tables.
                        </span>
                    )}
                </div>
            )}
        </div>
    )
}
