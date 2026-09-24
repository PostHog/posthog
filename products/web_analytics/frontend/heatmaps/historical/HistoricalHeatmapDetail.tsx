import { useEffect, useRef } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { DATE_TIME_FORMAT, formatDate } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import type { HeatmapAnalysisVariantApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { HistoricalHeatmapImage } from './HistoricalHeatmapImage'
import { variantDateRange, variantStatsLabel } from './variantLabels'

export function HistoricalHeatmapDetail({
    variant,
    index,
    total,
    timezone,
    backgroundUrl,
    loading,
    disabledReason,
    onClose,
    onNavigate,
    onChooseMoment,
}: {
    variant: HeatmapAnalysisVariantApi
    index: number
    total: number
    timezone: string
    backgroundUrl: string
    loading: boolean
    disabledReason?: string | null
    onClose: () => void
    onNavigate: (direction: -1 | 1) => void
    onChooseMoment: (momentId: string) => void
}): JSX.Element {
    const modalRef = useRef<HTMLDivElement | null>(null)
    useEffect(() => {
        modalRef.current?.querySelector('.LemonModal__content')?.scrollTo({ top: 0 })
    }, [variant.id])

    return (
        <LemonModal
            title={`Variant ${index + 1} of ${total}`}
            description={`${variantStatsLabel(variant)} · ${variantDateRange(variant, timezone)}`}
            width="72rem"
            onClose={onClose}
            contentRef={(element) => {
                modalRef.current = element
            }}
            data-attr="historical-heatmap-detail"
            footer={
                <div className="flex flex-wrap items-center justify-between gap-2 w-full">
                    <LemonButton type="tertiary" onClick={onClose}>
                        All variants
                    </LemonButton>
                    <div className="flex gap-2">
                        <LemonButton
                            icon={<IconChevronLeft />}
                            onClick={() => onNavigate(-1)}
                            disabled={index === 0}
                            data-attr="historical-heatmap-previous"
                        >
                            Previous
                        </LemonButton>
                        <LemonButton
                            sideIcon={<IconChevronRight />}
                            onClick={() => onNavigate(1)}
                            disabled={index === total - 1}
                            data-attr="historical-heatmap-next"
                        >
                            Next
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-muted">Screenshot</span>
                    <LemonSelect
                        size="small"
                        aria-label="Screenshot moment"
                        loading={loading}
                        disabledReason={disabledReason}
                        value={variant.alternatives[0]?.id}
                        options={variant.alternatives.map((moment) => ({
                            value: moment.id,
                            label: formatDate(dayjs(moment.timestamp).tz(timezone), DATE_TIME_FORMAT),
                        }))}
                        onChange={onChooseMoment}
                        tooltip={`Recorded time in ${timezone}`}
                        data-attr="historical-heatmap-screenshot"
                    />
                </div>
                <LemonButton
                    size="small"
                    type="secondary"
                    to={urls.replaySingle(variant.session_id, { unixTimestampMillis: variant.timestamp })}
                    data-attr="historical-heatmap-view-recording"
                >
                    View recording
                </LemonButton>
            </div>
            {variant.representative_replaced && (
                <LemonBanner type="warning" className="mb-3">
                    The saved screenshot is unavailable. Showing another recording of this variant.
                </LemonBanner>
            )}
            <HistoricalHeatmapImage key={backgroundUrl} variant={variant} backgroundUrl={backgroundUrl} />
        </LemonModal>
    )
}
