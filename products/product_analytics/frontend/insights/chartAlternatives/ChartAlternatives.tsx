import { useActions, useMountedLogic, useValues } from 'kea'
import { useRef } from 'react'

import { LemonButton, Popover } from '@posthog/lemon-ui'

import { ChartFilter } from 'lib/components/ChartFilter'

import type { InsightLogicProps } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import { ChartDisplayIcon } from './ChartDisplayIcon'
import { ChartGallery } from './ChartGallery'
import { chartPreviewsLogic } from './chartPreviewsLogic'

// Leaves the gallery 33rem of content box, just over the @lg breakpoint that puts three tiles in a row.
const GALLERY_WIDTH = 'w-[34rem] max-w-[calc(100vw-2rem)]'

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
}): JSX.Element {
    const logicProps = { editMode, embedded, inSharedMode, ...insightProps }
    const logic = useMountedLogic(chartAlternativesLogic(logicProps))
    useMountedLogic(chartPreviewsLogic(logicProps))
    const { canShowAlternatives, currentOption, galleryOpen, selectionDisabledReason } = useValues(logic)
    const { closeGallery, toggleGallery } = useActions(logic)
    const triggerRef = useRef<HTMLButtonElement>(null)

    if (!canShowAlternatives) {
        return <ChartFilter />
    }

    return (
        <Popover
            visible={galleryOpen}
            onClickOutside={(event) => {
                // A press on the trigger counts as outside, and would close then reopen on the click.
                if (!(event.target instanceof Node && triggerRef.current?.contains(event.target))) {
                    closeGallery()
                }
            }}
            placement="bottom-end"
            padded={false}
            overlay={
                <ChartGallery
                    className={GALLERY_WIDTH}
                    insightProps={insightProps}
                    editMode={editMode}
                    embedded={embedded}
                    inSharedMode={inSharedMode}
                />
            }
        >
            <LemonButton
                ref={triggerRef}
                size="small"
                type="secondary"
                active={galleryOpen}
                icon={currentOption ? <ChartDisplayIcon icon={currentOption.icon} /> : undefined}
                data-attr="chart-alternatives-all"
                disabledReason={selectionDisabledReason}
                onClick={toggleGallery}
            >
                {currentOption?.label ?? 'Chart type'}
            </LemonButton>
        </Popover>
    )
}
