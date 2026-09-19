import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import type { InsightLogicProps } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import { chartPreviewsLogic } from './chartPreviewsLogic'
import { ChartPreviewTile } from './ChartPreviewTile'

// Replaces the chart with a grid of every chart type rendered from the insight's own data while the gallery is open.
export function ChartGallery({
    children,
    editMode,
    embedded,
    inSharedMode,
    insightProps,
}: {
    children: ReactNode
    editMode?: boolean
    embedded: boolean
    inSharedMode?: boolean
    insightProps: InsightLogicProps
}): JSX.Element {
    const logicProps = { editMode, embedded, inSharedMode, ...insightProps }
    const alternativesLogic = useMountedLogic(chartAlternativesLogic(logicProps))
    const { galleryOpen, selectionDisabledReason } = useValues(alternativesLogic)
    const { selectChart } = useActions(alternativesLogic)
    const { previewGroups } = useValues(useMountedLogic(chartPreviewsLogic(logicProps)))

    if (!galleryOpen) {
        return <>{children}</>
    }

    const previews = previewGroups.flatMap((group) => group.previews)
    const unavailable = previews.filter((preview) => !!preview.option.disabledReason)
    const sections = previewGroups
        .map((group) => ({
            title: group.title,
            previews: group.previews.filter((preview) => !preview.option.disabledReason),
        }))
        .filter((group) => group.previews.length > 0)
    if (unavailable.length) {
        sections.push({ title: 'Not available', previews: unavailable })
    }

    return (
        <div className="flex flex-col gap-3 p-2" data-attr="chart-alternatives-gallery">
            {sections.map((section) => (
                <div key={section.title} className="flex flex-col gap-1.5">
                    <h5 className="m-0 text-xs font-semibold uppercase text-secondary">{section.title}</h5>
                    <div className="grid grid-cols-4 gap-2">
                        {section.previews.map((preview) => (
                            <ChartPreviewTile
                                key={preview.option.display}
                                preview={preview}
                                disabledReason={selectionDisabledReason}
                                onSelect={() =>
                                    selectChart(preview.option.display, preview.suggested ? 'recommended' : 'gallery')
                                }
                            />
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}
