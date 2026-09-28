import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import type { InsightLogicProps } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import type { ChartPreview } from './chartPreviewsLogic'
import { chartPreviewsLogic } from './chartPreviewsLogic'
import { ChartPreviewTile } from './ChartPreviewTile'

const GRID = 'grid grid-cols-1 gap-2 @sm:grid-cols-2 @lg:grid-cols-3'

export function ChartGallery({
    className,
    embedded,
    inSharedMode,
    insightProps,
}: {
    className?: string
    embedded: boolean
    inSharedMode?: boolean
    insightProps: InsightLogicProps
}): JSX.Element {
    const logicProps = { embedded, inSharedMode, ...insightProps }
    const alternativesLogic = useMountedLogic(chartAlternativesLogic(logicProps))
    const { selectionDisabledReason } = useValues(alternativesLogic)
    const { selectChart } = useActions(alternativesLogic)
    const previewsLogic = chartPreviewsLogic(logicProps)
    const { chartsShown, previews } = useValues(previewsLogic)
    const { startChartPreviews } = useActions(previewsLogic)
    useOnMountEffect(startChartPreviews)
    const suggested = previews.filter((preview) => preview.suggested)
    const remaining = previews.filter((preview) => !preview.suggested)

    const renderTile = (preview: ChartPreview, index: number): JSX.Element => (
        <ChartPreviewTile
            key={preview.option.display}
            preview={preview}
            showChart={index < chartsShown}
            disabledReason={selectionDisabledReason}
            onSelect={() => selectChart(preview.option.display, preview.suggested ? 'recommended' : 'gallery')}
        />
    )

    return (
        <div className={clsx('@container overflow-y-auto p-2', className)} data-attr="chart-alternatives-gallery">
            <div className="flex flex-col gap-3">
                {suggested.length > 0 && (
                    <div className={GRID}>{suggested.map((preview, index) => renderTile(preview, index))}</div>
                )}
                <div className={GRID}>
                    {remaining.map((preview, index) => renderTile(preview, suggested.length + index))}
                </div>
            </div>
        </div>
    )
}
