import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'

import type { InsightLogicProps } from '~/types'

import type { ChartPreview } from './chartAlternativesLogic'
import { chartAlternativesLogic } from './chartAlternativesLogic'
import { ChartPreviewTile } from './ChartPreviewTile'

const GRID = 'grid grid-cols-1 gap-2 @sm:grid-cols-2 @lg:grid-cols-3'

export function ChartGallery({
    className,
    editMode,
    embedded,
    inSharedMode,
    insightProps,
}: {
    className?: string
    editMode?: boolean
    embedded: boolean
    inSharedMode?: boolean
    insightProps: InsightLogicProps
}): JSX.Element {
    const logic = useMountedLogic(chartAlternativesLogic({ editMode, embedded, inSharedMode, ...insightProps }))
    const { previewGroups, selectionDisabledReason } = useValues(logic)
    const { selectChart } = useActions(logic)

    const suggestedGroup = previewGroups.find((group) => group.title === 'Suggested')
    const suggested = suggestedGroup?.previews ?? []
    const rest = previewGroups.filter((group) => group !== suggestedGroup).flatMap((group) => group.previews)
    const ordered = [
        ...rest.filter((preview) => !preview.option.disabledReason),
        ...rest.filter((preview) => !!preview.option.disabledReason),
    ]

    const renderTile = (preview: ChartPreview): JSX.Element => (
        <ChartPreviewTile
            key={preview.option.display}
            preview={preview}
            disabledReason={selectionDisabledReason}
            onSelect={() => selectChart(preview.option.display, preview.suggested ? 'recommended' : 'gallery')}
        />
    )

    return (
        <div className={clsx('@container overflow-y-auto p-2', className)} data-attr="chart-alternatives-gallery">
            <div className="flex flex-col gap-3">
                {suggested.length > 0 && <div className={GRID}>{suggested.map(renderTile)}</div>}
                <div className={GRID}>{ordered.map(renderTile)}</div>
            </div>
        </div>
    )
}
