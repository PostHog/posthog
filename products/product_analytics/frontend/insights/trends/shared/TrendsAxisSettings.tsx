import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { DEFAULT_Y_AXIS_ID, useChartLayout } from '@posthog/quill-charts'

import { ChartAxisControls } from 'lib/charts/ChartAxisControls'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { InsightLogicProps } from '~/types'

import { trendsAxisSettingsLogic } from './trendsAxisSettingsLogic'

const TrendsAxisSettingsModal = lazyWithRetry(() =>
    import('./TrendsAxisSettingsModal').then(({ TrendsAxisSettingsModal }) => ({ default: TrendsAxisSettingsModal }))
)

export function TrendsAxisSettings({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { series, yGutters } = useChartLayout()
    const { axis, canEditInsight, hasOverrides } = useValues(trendsAxisSettingsLogic(insightProps))
    const { openModal } = useActions(trendsAxisSettingsLogic(insightProps))
    if (!canEditInsight || hasOverrides) {
        return null
    }
    return (
        <>
            <ChartAxisControls
                axes={['left', 'right']}
                onEdit={(axis) => {
                    if (axis !== 'x') {
                        openModal(
                            axis,
                            series.map((item) => ({
                                id: item.key,
                                label: item.label,
                                position:
                                    yGutters.find((gutter) => gutter.axisId === (item.yAxisId ?? DEFAULT_Y_AXIS_ID))
                                        ?.side ?? 'left',
                            }))
                        )
                    }
                }}
            />
            {axis && (
                <Suspense fallback={null}>
                    <TrendsAxisSettingsModal insightProps={insightProps} />
                </Suspense>
            )}
        </>
    )
}
