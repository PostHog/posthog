import clsx from 'clsx'

import { IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import {
    formatConvertedCount,
    formatConvertedPercentage,
    formatDroppedOffCount,
    formatDroppedOffPercentage,
    getTooltipTitleForConverted,
    getTooltipTitleForDroppedOff,
} from 'scenes/funnels/funnelUtils'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'

import { type Noun } from '~/models/groupsModel'
import type { FunnelsFilter } from '~/queries/schema/schema-general'
import { type FunnelStepWithConversionMetrics } from '~/types'

interface StepFooterProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    funnelsFilter: FunnelsFilter | null | undefined
    aggregationTargetLabel: Noun
    isOptional: boolean
    showPersonsModal: boolean
    onOpenConverted: () => void
    onOpenDroppedOff: () => void
}

export function StepFooter({
    step,
    stepIndex,
    funnelsFilter,
    aggregationTargetLabel,
    isOptional,
    showPersonsModal,
    onOpenConverted,
    onOpenDroppedOff,
}: StepFooterProps): JSX.Element {
    const isFirstStep = stepIndex === 0

    return (
        <div className={clsx('flex flex-wrap items-center gap-2 leading-5', isOptional && 'opacity-60')}>
            <Tooltip
                title={getTooltipTitleForConverted(funnelsFilter, aggregationTargetLabel, stepIndex)}
                placement="bottom"
            >
                <ValueInspectorButton onClick={showPersonsModal ? onOpenConverted : undefined}>
                    <IconTrendingFlat style={{ color: 'var(--success)' }} className="mr-1 text-xl align-bottom" />
                    <b>{formatConvertedCount(step, aggregationTargetLabel)}</b>
                </ValueInspectorButton>{' '}
                {!isFirstStep && (
                    <span className="text-secondary grow">{`(${formatConvertedPercentage(step)}) completed step`}</span>
                )}
            </Tooltip>
            {!isFirstStep && (
                <Tooltip title={getTooltipTitleForDroppedOff(funnelsFilter, aggregationTargetLabel)} placement="bottom">
                    <ValueInspectorButton onClick={showPersonsModal ? onOpenDroppedOff : undefined}>
                        <IconTrendingFlatDown
                            style={{ color: 'var(--danger)' }}
                            className="mr-1 text-xl align-bottom"
                        />
                        <b>{formatDroppedOffCount(step, aggregationTargetLabel)}</b>
                    </ValueInspectorButton>{' '}
                    <span className="text-secondary">{`(${formatDroppedOffPercentage(step)}) dropped off`}</span>
                </Tooltip>
            )}
        </div>
    )
}
