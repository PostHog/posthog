import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useState } from 'react'

import type { InsightLogicProps } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import type { ChartPreview } from './chartPreviewsLogic'
import { chartPreviewsLogic } from './chartPreviewsLogic'
import { ChartPreviewTile } from './ChartPreviewTile'

const GRID = 'grid grid-cols-1 gap-2 @sm:grid-cols-2 @lg:grid-cols-3'

// Each tile mounts a full chart, so mounting them all in one render freezes slower devices before the gallery shows.
function useCountUpOnePerFrame(total: number): number {
    const [count, setCount] = useState(0)
    useEffect(() => {
        if (count >= total) {
            return
        }
        let timeout: ReturnType<typeof setTimeout> | undefined
        // A timeout after the frame lets the browser paint the previous tile before the next one mounts.
        const frame = requestAnimationFrame(() => {
            timeout = setTimeout(() => setCount((current) => current + 1))
        })
        return () => {
            cancelAnimationFrame(frame)
            clearTimeout(timeout)
        }
    }, [count, total])
    return count
}

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
    const { previews } = useValues(chartPreviewsLogic(logicProps))
    const suggested = previews.filter((preview) => preview.suggested)
    const remaining = previews.filter((preview) => !preview.suggested)
    const chartsShown = useCountUpOnePerFrame(previews.length)

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
