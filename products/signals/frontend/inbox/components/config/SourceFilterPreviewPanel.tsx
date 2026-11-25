import { LemonBanner, LemonBannerProps, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type {
    SourceFilterPreviewResponseApi,
    SourceFilterPreviewStatusEnumApi,
} from 'products/signals/frontend/generated/api.schemas'

import { SourceFilterPreviewResults } from './SourceFilterPreviewResults'

/** Why a preview request got no response at all. A response that arrives carries its own `status`. */
export type SourceFilterPreviewRequestError = 'throttled' | 'failed'

export interface SourceFilterPreviewPanelProps {
    /** The latest preview response. It stays while a newer one loads. Null until the first one arrives. */
    result: SourceFilterPreviewResponseApi | null
    loading: boolean
    requestError: SourceFilterPreviewRequestError | null
    onRetry: () => void
    sourceLabel: string
    /** What one record of the source is called, from the catalog `source_type`, such as "issue". */
    noun: string
}

interface PreviewNotice {
    type: LemonBannerProps['type']
    message: string
    retry?: boolean
}

function previewNotice(
    result: SourceFilterPreviewResponseApi | null,
    requestError: SourceFilterPreviewRequestError | null,
    sourceLabel: string,
    nouns: string
): PreviewNotice | null {
    if (requestError === 'throttled') {
        return { type: 'info', message: 'Too many previews in a short time. The preview updates again shortly.' }
    }
    if (requestError === 'failed') {
        return {
            type: 'error',
            message: "Couldn't load the preview. Check your connection and try again.",
            retry: true,
        }
    }
    if (!result) {
        return null
    }
    const notices: Partial<Record<SourceFilterPreviewStatusEnumApi, PreviewNotice>> = {
        invalid_expression: {
            type: 'error',
            message: result.error ?? "This filter isn't valid. Check the field names, quotes and brackets.",
        },
        not_connected: {
            type: 'info',
            message: `${sourceLabel} isn't syncing data to this project, so there are no ${nouns} to preview. You can still save the filter.`,
        },
        not_synced: {
            type: 'info',
            message: `${sourceLabel} hasn't finished its first sync, so there are no ${nouns} to preview yet. You can still save the filter.`,
        },
        access_denied: {
            type: 'info',
            message: `You don't have access to this project's ${sourceLabel} data, so the preview can't show ${nouns}. You can still save the filter.`,
        },
        incompatible_table: {
            type: 'warning',
            message: `The synced ${sourceLabel} table doesn't have the columns these fields read, so the preview can't run. Contact support if this keeps happening.`,
        },
        query_failed: {
            type: 'error',
            message: `The preview couldn't run on your ${sourceLabel} data. Try again in a moment.`,
            retry: true,
        },
    }
    return notices[result.status] ?? null
}

/** What a filter expression does to the source's recent records: how many pass, and the newest of each side. */
export function SourceFilterPreviewPanel({
    result,
    loading,
    requestError,
    onRetry,
    sourceLabel,
    noun,
}: SourceFilterPreviewPanelProps): JSX.Element {
    const nouns = `${noun}s`
    const notice = previewNotice(result, requestError, sourceLabel, nouns)

    let content: JSX.Element
    if (notice) {
        content = (
            <LemonBanner
                type={notice.type}
                action={
                    notice.retry
                        ? {
                              children: 'Retry',
                              onClick: onRetry,
                              loading,
                              'data-attr': 'signal-source-filter-preview-retry',
                          }
                        : undefined
                }
            >
                {notice.message}
            </LemonBanner>
        )
    } else if (!result) {
        content = (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-8" />
                <LemonSkeleton repeat={4} className="h-6" />
            </div>
        )
    } else if (result.total_count === 0) {
        content = (
            <div className="rounded border border-dashed border-primary p-4 text-center text-sm text-secondary">
                {`No ${sourceLabel} ${nouns} from the last ${pluralize(result.lookback_days, 'day')} to preview. The filter applies to new ${nouns} once you save it.`}
            </div>
        )
    } else {
        content = <SourceFilterPreviewResults result={result} sourceLabel={sourceLabel} noun={noun} />
    }

    return (
        <div className="flex min-w-0 flex-col gap-2 @container" aria-busy={loading}>
            <div className="flex min-h-6 items-center justify-between gap-2">
                <span className="text-xs font-semibold text-default">
                    {result ? `Last ${pluralize(result.lookback_days, 'day')}` : `Recent ${nouns}`}
                </span>
                {loading && (result || requestError) && (
                    <span className="flex items-center gap-1 text-xs text-secondary">
                        <Spinner />
                        <span>Updating</span>
                    </span>
                )}
            </div>
            {content}
        </div>
    )
}
