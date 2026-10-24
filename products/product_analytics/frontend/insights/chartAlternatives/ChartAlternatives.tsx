import { useActions, useMountedLogic, useValues } from 'kea'
import { useRef } from 'react'

import { LemonButton, Popover } from '@posthog/lemon-ui'

import { ChartFilter } from 'lib/components/ChartFilter'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { InsightLogicProps } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import { ChartDisplayIcon } from './ChartDisplayIcon'
import { ChartGallery } from './ChartGallery'
import { chartPreviewsLogic } from './chartPreviewsLogic'
import { QuillChartAlternatives } from './QuillChartAlternatives'

// Leaves the gallery 33rem of content box, just over the @lg breakpoint that puts three tiles in a row.
const GALLERY_WIDTH = 'w-[34rem] max-w-[calc(100vw-2rem)]'

export function ChartAlternatives({
    embedded,
    inSharedMode,
    insightProps,
}: {
    embedded: boolean
    inSharedMode?: boolean
    insightProps: InsightLogicProps
}): JSX.Element {
    const logicProps = { embedded, inSharedMode, ...insightProps }
    const logic = useMountedLogic(chartAlternativesLogic(logicProps))
    useMountedLogic(chartPreviewsLogic(logicProps))
    const { canShowAlternatives, currentOption, galleryOpen, selectionDisabledReason } = useValues(logic)
    const { closeGallery, openGallery, reportChartMenuOpened, toggleGallery } = useActions(logic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!canShowAlternatives) {
        return <ChartFilter onOpen={reportChartMenuOpened} />
    }

    const gallery = (
        <ChartGallery
            className={GALLERY_WIDTH}
            insightProps={insightProps}
            embedded={embedded}
            inSharedMode={inSharedMode}
        />
    )

    if (todayRailNav) {
        return (
            <QuillChartAlternatives
                open={galleryOpen}
                onOpenChange={(open) => (open ? openGallery() : closeGallery())}
                currentOption={currentOption}
                disabledReason={selectionDisabledReason}
                gallery={gallery}
            />
        )
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
            overlay={gallery}
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
