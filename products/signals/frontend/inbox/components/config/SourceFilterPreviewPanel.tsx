import { useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonBanner, LemonSegmentedButton, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'

import type { SourceFilterPreviewResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { SourceFilterPreviewRecordRow } from './SourceFilterPreviewRecordRow'

/** Why a preview request got no response at all. A response that arrives carries its own `status`. */
export type SourceFilterPreviewRequestError = 'throttled' | 'failed'

export interface SourceFilterPreviewPanelProps {
    /** The latest preview response. It stays while a newer one loads. Null until the first one arrives. */
    result: SourceFilterPreviewResponseApi | null
    /** A preview request is in flight. */
    loading: boolean
    requestError: SourceFilterPreviewRequestError | null
    onRetry: () => void
    /** The roster label of the source, such as "Linear". */
    sourceLabel: string
    /** What one record of the source is called, from the catalog `source_type`, such as "issue". */
    noun: string
}

type PreviewSide = 'passing' | 'excluded'

/** What a filter expression does to the source's recent records: how many pass, and the newest of each side. */
export function SourceFilterPreviewPanel({
    result,
    loading,
    requestError,
    onRetry,
    sourceLabel,
    noun,
}: SourceFilterPreviewPanelProps): JSX.Element {
    const [side, setSide] = useState<PreviewSide>('excluded')
    const nouns = `${noun}s`
    const retryAction = {
        children: 'Retry',
        onClick: onRetry,
        loading,
        'data-attr': 'signal-source-filter-preview-retry',
    }

    let content: JSX.Element
    if (requestError === 'throttled') {
        content = (
            <LemonBanner type="info">Too many previews in a short time. The preview updates again shortly.</LemonBanner>
        )
    } else if (requestError === 'failed') {
        content = (
            <LemonBanner type="error" action={retryAction}>
                Couldn't load the preview. Check your connection and try again.
            </LemonBanner>
        )
    } else if (!result) {
        content = (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-8" />
                <LemonSkeleton repeat={4} className="h-6" />
            </div>
        )
    } else if (result.status === 'invalid_expression') {
        content = (
            <LemonBanner type="error">
                {result.error ?? "This filter isn't valid. Check the field names, quotes and brackets."}
            </LemonBanner>
        )
    } else if (result.status === 'not_connected') {
        content = (
            <LemonBanner type="info">
                {`${sourceLabel} isn't syncing data to this project, so there are no ${nouns} to preview. You can still save the filter.`}
            </LemonBanner>
        )
    } else if (result.status === 'not_synced') {
        content = (
            <LemonBanner type="info">
                {`${sourceLabel} hasn't finished its first sync, so there are no ${nouns} to preview yet. You can still save the filter.`}
            </LemonBanner>
        )
    } else if (result.status === 'access_denied') {
        content = (
            <LemonBanner type="info">
                {`You don't have access to this project's ${sourceLabel} data, so the preview can't show ${nouns}. You can still save the filter.`}
            </LemonBanner>
        )
    } else if (result.status === 'incompatible_table') {
        content = (
            <LemonBanner type="warning">
                {`The synced ${sourceLabel} table doesn't have the columns these fields read, so the preview can't run. Contact support if this keeps happening.`}
            </LemonBanner>
        )
    } else if (result.status === 'query_failed') {
        content = (
            <LemonBanner type="error" action={retryAction}>
                {`The preview couldn't run on your ${sourceLabel} data. Try again in a moment.`}
            </LemonBanner>
        )
    } else if (result.total_count === 0) {
        content = (
            <div className="rounded border border-dashed border-primary p-4 text-center text-sm text-secondary">
                {`No ${sourceLabel} ${nouns} from the last ${pluralize(result.lookback_days, 'day')} to preview. The filter applies to new ${nouns} once you save it.`}
            </div>
        )
    } else {
        const records = side === 'passing' ? result.passing : result.excluded
        const malformed = result.malformed_count
        content = (
            <>
                <LemonSegmentedButton
                    fullWidth
                    size="small"
                    value={side}
                    onChange={setSide}
                    options={[
                        {
                            value: 'passing',
                            label: `Passes ${humanFriendlyNumber(result.passing_count)}`,
                            icon: <IconCheck />,
                            'data-attr': 'signal-source-filter-preview-passing',
                        },
                        {
                            value: 'excluded',
                            label: `Excluded ${humanFriendlyNumber(result.excluded_count)}`,
                            icon: <IconX />,
                            'data-attr': 'signal-source-filter-preview-excluded',
                        },
                    ]}
                />
                {records.length > 0 ? (
                    <ul className="flex flex-col divide-y divide-primary">
                        {records.map((record) => (
                            <SourceFilterPreviewRecordRow key={record.id} record={record} noun={noun} />
                        ))}
                    </ul>
                ) : (
                    <p className="m-0 py-3 text-sm text-secondary">
                        {side === 'passing'
                            ? `No recent ${nouns} pass, so no new reports would come from ${sourceLabel}.`
                            : `No recent ${nouns} are excluded.`}
                    </p>
                )}
                {side === 'excluded' && malformed > 0 && (
                    <p className="m-0 text-xs text-muted">
                        {malformed === 1
                            ? `1 ${noun} is unreadable. It holds a value this filter can't read, so it never passes.`
                            : `${humanFriendlyNumber(malformed)} ${nouns} are unreadable. They hold a value this filter can't read, so they never pass.`}
                    </p>
                )}
                <p className="m-0 text-xs text-muted">
                    {`Shows the 10 newest of each. ${capitalizeFirstLetter(nouns)} that pass can still be skipped by guidance or as duplicates.`}
                </p>
            </>
        )
    }

    const showsSkeleton = !requestError && !result
    return (
        <div className="flex min-w-0 flex-col gap-2 @container" aria-busy={loading}>
            <div className="flex min-h-6 items-center justify-between gap-2">
                <span className="text-xs font-semibold text-default">
                    {result ? `Last ${pluralize(result.lookback_days, 'day')}` : `Recent ${nouns}`}
                </span>
                {loading && !showsSkeleton && (
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
