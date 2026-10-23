import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconTrending } from '@posthog/icons'
import { LemonRow } from '@posthog/lemon-ui'

import { IconFlare, IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { percentage } from 'lib/utils/numbers'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartParams } from '~/types'

import { computeComparisonDisplay } from 'products/product_analytics/frontend/insights/shared/BoldNumber/BoldNumber'
import { Textfit } from 'products/product_analytics/frontend/insights/shared/BoldNumber/Textfit'

import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'

export function FunnelBoldNumber({ showPersonsModal = true }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const {
        conversionMetrics,
        previousPeriodTotalRate,
        isComparedFunnel,
        isBreakdownCompareFunnel,
        visibleStepsWithConversionMetrics,
    } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep } = useActions(funnelPersonsModalLogic(insightProps))

    const lastStepIndex = visibleStepsWithConversionMetrics.length - 1
    const canOpenConvertedPersons = showPersonsModal && canOpenPersonModal && lastStepIndex > 0
    const { percentageDiff, hasComparableDiff, displayText } = computeComparisonDisplay(
        conversionMetrics.totalRate,
        previousPeriodTotalRate
    )

    return (
        <div className="BoldNumber ph-no-capture">
            <button
                type="button"
                className={clsx('BoldNumber__value', canOpenConvertedPersons ? 'cursor-pointer' : 'cursor-default')}
                data-attr="funnel-bold-number-value"
                disabled={!canOpenConvertedPersons}
                onClick={() =>
                    openPersonsModalForStep({
                        step: visibleStepsWithConversionMetrics[lastStepIndex],
                        stepIndex: lastStepIndex,
                        converted: true,
                    })
                }
            >
                <Textfit min={32} max={64}>
                    {percentage(conversionMetrics.totalRate, 2, true)}
                </Textfit>
            </button>
            {isComparedFunnel && !isBreakdownCompareFunnel && (
                <LemonRow
                    icon={
                        !hasComparableDiff || percentageDiff === null ? (
                            <IconFlare />
                        ) : percentageDiff > 0 ? (
                            <IconTrending />
                        ) : percentageDiff < 0 ? (
                            <IconTrendingDown />
                        ) : (
                            <IconTrendingFlat />
                        )
                    }
                    className="BoldNumber__comparison"
                    data-attr="funnel-bold-number-comparison"
                    fullWidth
                    center
                >
                    {displayText} previous period
                </LemonRow>
            )}
        </div>
    )
}
