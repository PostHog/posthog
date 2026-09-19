import { useActions, useMountedLogic, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { InsightLogicProps } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import { ChartDisplayIcon } from './ChartDisplayIcon'

export function ChartAlternatives({
    editMode,
    embedded,
    inSharedMode,
    insightProps,
}: {
    editMode?: boolean
    embedded: boolean
    inSharedMode?: boolean
    insightProps: InsightLogicProps
}): JSX.Element | null {
    const logic = useMountedLogic(chartAlternativesLogic({ editMode, embedded, inSharedMode, ...insightProps }))
    const { canShowAlternatives, currentOption, galleryOpen, selectionDisabledReason } = useValues(logic)
    const { toggleGallery } = useActions(logic)

    if (!canShowAlternatives) {
        return null
    }

    return (
        <LemonButton
            size="small"
            type="secondary"
            active={galleryOpen}
            icon={galleryOpen ? <IconX /> : currentOption ? <ChartDisplayIcon icon={currentOption.icon} /> : undefined}
            data-attr="chart-alternatives-all"
            disabledReason={selectionDisabledReason}
            onClick={toggleGallery}
        >
            {galleryOpen ? 'Cancel' : 'Switch chart'}
        </LemonButton>
    )
}
