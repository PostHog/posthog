import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'

import type { InsightLogicProps } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import { ChartPreviewTile } from './ChartPreviewTile'

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
        <div
            className={clsx('@container flex flex-col gap-3 overflow-y-auto p-2', className)}
            data-attr="chart-alternatives-gallery"
        >
            {sections.map((section) => (
                <div key={section.title} className="flex flex-col gap-1.5">
                    <h5 className="m-0 text-xs font-semibold uppercase text-secondary">{section.title}</h5>
                    <div className="grid grid-cols-1 gap-2 @sm:grid-cols-2 @lg:grid-cols-3">
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
