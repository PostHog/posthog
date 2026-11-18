import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { HEATMAP_TYPES, heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import type { HeatmapKind } from 'lib/components/heatmaps/types'
import { humanFriendlyLargeNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { HeatmapEmptyDiagnosis } from './heatmapCoverage'
import { heatmapCoverageLogic } from './heatmapCoverageLogic'

const interactionNoun = (type: HeatmapKind): string => HEATMAP_TYPES[type].label.toLowerCase()

function DiagnosisMessage({
    diagnosis,
    noun,
    width,
    canMatchPage,
}: {
    diagnosis: HeatmapEmptyDiagnosis
    noun: string
    width: number
    canMatchPage: boolean
}): JSX.Element {
    const { applySuggestion } = useActions(heatmapCoverageLogic)
    const { rawHeatmapLoading } = useValues(heatmapDataLogic({ context: 'in-app' }))

    const suggestionButton = (label: string, dataAttr: string, url?: string): JSX.Element => (
        <LemonButton
            type="secondary"
            size="xsmall"
            loading={rawHeatmapLoading}
            onClick={() => applySuggestion(url)}
            data-attr={dataAttr}
        >
            {label}
        </LemonButton>
    )

    switch (diagnosis.reason) {
        case 'capture_off':
            return (
                <span>
                    Heatmap capture is turned off for this project, so there is no data to show.{' '}
                    <Link to={urls.settings('environment-heatmaps')}>Turn it on in settings</Link>.
                </span>
            )
        case 'other_widths':
            return (
                <div className="flex flex-wrap items-center gap-2">
                    <span>
                        No {noun} at {width}px. {percentage(diagnosis.share, 0)} of this page's {noun} are at about{' '}
                        {diagnosis.width}px.
                    </span>
                    {suggestionButton(`Show ${diagnosis.width}px`, 'heatmap-empty-show-width')}
                </div>
            )
        case 'other_types':
            return (
                <div className="flex flex-wrap items-center gap-2">
                    <span>
                        No {noun} for this page, but it has {humanFriendlyLargeNumber(diagnosis.count)}{' '}
                        {interactionNoun(diagnosis.type)}.
                    </span>
                    {suggestionButton(`Show ${interactionNoun(diagnosis.type)}`, 'heatmap-empty-show-type')}
                </div>
            )
        case 'other_dates':
            return (
                <span>
                    No data for this page in the selected dates. It has {humanFriendlyLargeNumber(diagnosis.count)}{' '}
                    interactions in the last 90 days, so try a longer date range.
                </span>
            )
        case 'other_query_strings':
            return (
                <div className="flex flex-wrap items-center gap-2">
                    <span>
                        No data for this exact URL. {humanFriendlyLargeNumber(diagnosis.count)} interactions match this
                        page with a different query string.
                        {canMatchPage ? '' : ' Add * to the end of the heatmap data URL to include them.'}
                    </span>
                    {canMatchPage ? suggestionButton('Match this page', 'heatmap-empty-match-page') : null}
                </div>
            )
        case 'similar_urls':
            return (
                <div className="flex flex-col gap-1">
                    <span>No data for this URL. These similar URLs have data:</span>
                    <div className="flex flex-wrap gap-1">
                        {diagnosis.urls.map(({ url }) => (
                            <span key={url} className="max-w-full truncate">
                                {suggestionButton(url, 'heatmap-empty-similar-url', url)}
                            </span>
                        ))}
                    </div>
                </div>
            )
        case 'other_filters':
            return (
                <span>
                    This page has {noun} at {width}px, but none match your filters. Try removing the test account,
                    cohort or event filters.
                </span>
            )
        case 'no_data':
            return (
                <span>
                    No heatmap data for this URL in the last 90 days. Check that the URL matches what your visitors see
                    and that heatmap capture runs on this page.
                </span>
            )
    }
}

export function HeatmapEmptyState({ lockedWidth }: { lockedWidth?: number }): JSX.Element {
    const { emptyDiagnosis, emptyDiagnosisLoading, hasValidReplayIframeData, recordingUrlMatchMode } =
        useValues(heatmapCoverageLogic)
    const { heatmapFilters, analysisWidth } = useValues(heatmapDataLogic({ context: 'in-app' }))

    if (emptyDiagnosisLoading) {
        return (
            <p className="text-sm text-muted mt-2 mb-0 flex items-center gap-1">
                <Spinner /> No interactions found. Checking where this page's data is.
            </p>
        )
    }
    if (!emptyDiagnosis) {
        return (
            <p className="text-sm text-muted mt-2 mb-0">
                {lockedWidth
                    ? 'No interactions found at this screen width. Try a different date range, or adjust your filters in Heatmap settings.'
                    : 'No interactions found at this screen width. Try another screen width, a different date range, or adjust your filters in Heatmap settings.'}
            </p>
        )
    }
    return (
        <LemonBanner type="info" className="mt-2">
            <DiagnosisMessage
                diagnosis={emptyDiagnosis}
                noun={interactionNoun(heatmapFilters.type ?? 'click')}
                width={analysisWidth}
                canMatchPage={hasValidReplayIframeData && recordingUrlMatchMode !== 'page'}
            />
        </LemonBanner>
    )
}
