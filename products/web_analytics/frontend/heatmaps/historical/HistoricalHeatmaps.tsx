import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonTag, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Popover } from 'lib/lemon-ui/Popover'
import { formatDateTimeRange } from 'lib/utils/datetime'
import { pluralize } from 'lib/utils/strings'
import { toParams } from 'lib/utils/url'

import { getHeatmapAnalysesBackgroundRetrieveUrl } from 'products/web_analytics/frontend/generated/api'
import type { HeatmapAnalysisVariantApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { HeatmapFilterControls } from '../components/HeatmapFilterControls'
import { HistoricalHeatmapDetail } from './HistoricalHeatmapDetail'
import { historicalHeatmapLogic } from './historicalHeatmapLogic'
import { HistoricalHeatmapVariant } from './HistoricalHeatmapVariant'

export function HistoricalHeatmaps({
    heatmapId,
    disabledReason,
}: {
    heatmapId: string
    disabledReason?: string | null
}): JSX.Element {
    const logic = historicalHeatmapLogic({ heatmapId })
    const {
        result,
        resultLoading,
        error,
        processing,
        visibleCount,
        currentTeamIdStrict,
        timezone,
        filtersChanged,
        sortedVariants,
        selectedVariant,
        selectedVariantIndex,
    } = useValues(logic)
    const { startAnalysis, showMore, changeRepresentative, selectVariant, navigateVariant } = useActions(logic)
    const [detailsOpen, setDetailsOpen] = useState(false)
    const backgroundUrl = (variant: HeatmapAnalysisVariantApi): string =>
        `${getHeatmapAnalysesBackgroundRetrieveUrl(String(currentTeamIdStrict), result!.analysis.id, variant.id)}?${toParams({ moment: variant.timestamp, session: variant.session_id })}`
    const needsUpdate =
        !result || filtersChanged || result.analysis.status === 'failed' || result.analysis.status === 'unavailable'

    return (
        <div className="@container/historical flex flex-col gap-4 min-w-0">
            <HeatmapFilterControls
                actions={
                    <LemonButton
                        type={needsUpdate ? 'primary' : 'secondary'}
                        size="small"
                        icon={result && !needsUpdate ? <IconRefresh /> : undefined}
                        disabledReason={disabledReason}
                        loading={resultLoading || processing}
                        onClick={startAnalysis}
                        data-attr="historical-heatmap-refresh"
                    >
                        {processing
                            ? 'Analyzing'
                            : !result
                              ? 'Find variants'
                              : needsUpdate
                                ? 'Update results'
                                : 'Refresh'}
                    </LemonButton>
                }
            />
            {filtersChanged && result && !processing && (
                <div role="status" className="text-sm text-muted">
                    Filters changed. Update results to apply them.
                </div>
            )}
            {error && <LemonBanner type="error">{error} Try again.</LemonBanner>}
            {processing || (!result && resultLoading) ? (
                <div className="flex flex-col items-center justify-center gap-3 py-16" role="status">
                    <Spinner />
                    <div className="font-semibold">Finding page variants</div>
                    <p className="text-muted text-center mb-0">
                        This may take a few minutes. You can leave this page and come back.
                    </p>
                </div>
            ) : !result ? (
                !error && (
                    <LemonCard hoverEffect={false} className="text-center py-12">
                        <h2>See how your page changed</h2>
                        <p className="text-muted mb-0">
                            Choose dates, then find page variants and their click heatmaps from Session replay.
                        </p>
                    </LemonCard>
                )
            ) : result.analysis.status === 'failed' ? (
                <LemonBanner type="error">
                    {result.analysis.error || "Couldn't analyze these recordings. Try a shorter date range."}
                </LemonBanner>
            ) : (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                            <h2 className="mb-0">{pluralize(sortedVariants.length, 'page variant')}</h2>
                            <span className="text-muted text-sm">{`${result.analyzed_visits.toLocaleString()} recorded visits`}</span>
                            {result.analysis.status === 'partial' && (
                                <LemonTag type="warning">Sampled results</LemonTag>
                            )}
                        </div>
                        <Popover
                            visible={detailsOpen}
                            onClickOutside={() => setDetailsOpen(false)}
                            placement="bottom-end"
                            overlay={
                                <div className="p-3 max-w-96 text-sm">
                                    <h3 className="mb-2">About this data</h3>
                                    <p>
                                        Click heatmaps use recorded visits. The combined view includes all captured
                                        heatmap traffic.
                                    </p>
                                    <p>
                                        Screenshots reconstruct the recorded page with replay masking. External images
                                        and styles may have changed. Fixed elements and clicks that cannot be aligned
                                        are excluded.
                                    </p>
                                    {result.analysis.status === 'partial' && (
                                        <p>
                                            This analysis reached a sampling or processing limit. Use a shorter date
                                            range to cover more matching visits.
                                        </p>
                                    )}
                                    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 mb-0">
                                        <dt>Recorded visits</dt>
                                        <dd className="m-0 text-right">{result.analyzed_visits}</dd>
                                        <dt>Recordings skipped</dt>
                                        <dd className="m-0 text-right">{result.analysis.excluded_recordings}</dd>
                                        <dt>Recordings unavailable</dt>
                                        <dd className="m-0 text-right">{result.unavailable_recordings}</dd>
                                        <dt>Clicks excluded</dt>
                                        <dd className="m-0 text-right">{result.excluded_clicks}</dd>
                                        <dt>Screen width</dt>
                                        <dd className="m-0 text-right">{`${result.analysis.viewport_width}px`}</dd>
                                    </dl>
                                    <p className="text-muted mt-3 mb-0 break-words">
                                        {`${formatDateTimeRange(dayjs(result.analysis.date_from).tz(timezone), dayjs(result.analysis.date_to).tz(timezone))} (${timezone})`}
                                    </p>
                                </div>
                            }
                        >
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={<IconInfo />}
                                onClick={() => setDetailsOpen(!detailsOpen)}
                                aria-expanded={detailsOpen}
                                data-attr="historical-heatmap-data-details"
                            >
                                About this data
                            </LemonButton>
                        </Popover>
                    </div>
                    {!!(result.unavailable_recordings || result.analysis.excluded_recordings) &&
                        !!sortedVariants.length && (
                            <LemonBanner type="warning">
                                Some recordings couldn't be included. See About this data for coverage.
                            </LemonBanner>
                        )}
                    {!sortedVariants.length ? (
                        <LemonCard hoverEffect={false} className="text-center py-12">
                            <h3>
                                {result.analysis.status === 'unavailable'
                                    ? 'These recordings are no longer available'
                                    : 'No page variants found'}
                            </h3>
                            <p className="text-muted mb-0">
                                {result.analysis.status === 'unavailable'
                                    ? 'Choose more recent dates and update results.'
                                    : 'Try another date range or screen width, or remove a filter.'}
                            </p>
                        </LemonCard>
                    ) : (
                        <div className="grid grid-cols-1 @min-[36rem]/historical:grid-cols-2 @min-[64rem]/historical:grid-cols-3 gap-4">
                            {sortedVariants.slice(0, visibleCount).map((variant, index) => (
                                <HistoricalHeatmapVariant
                                    key={variant.id}
                                    variant={variant}
                                    timezone={timezone}
                                    index={index}
                                    onSelect={() => selectVariant(variant.id)}
                                    backgroundUrl={backgroundUrl(variant)}
                                />
                            ))}
                        </div>
                    )}
                    {sortedVariants.length > visibleCount && (
                        <LemonButton onClick={showMore} type="secondary" className="self-start">
                            Show more variants
                        </LemonButton>
                    )}
                    {selectedVariant && (
                        <HistoricalHeatmapDetail
                            variant={selectedVariant}
                            index={selectedVariantIndex}
                            total={sortedVariants.length}
                            timezone={timezone}
                            backgroundUrl={backgroundUrl(selectedVariant)}
                            loading={resultLoading}
                            disabledReason={disabledReason}
                            onChooseMoment={(momentId) => changeRepresentative(selectedVariant.id, momentId)}
                            onNavigate={navigateVariant}
                            onClose={() => selectVariant(null)}
                        />
                    )}
                </>
            )}
        </div>
    )
}
