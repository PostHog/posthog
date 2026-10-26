import { useValues } from 'kea'

import { ReferenceLines, useChartLayout } from '@posthog/quill-charts'

import { insightLogic } from 'scenes/insights/insightLogic'

import { goalLinesToReferenceLines } from '../trends/shared/goalLinesAdapter'
import { funnelDataLogic } from './funnelDataLogic'

export function FunnelGoalLines(): JSX.Element {
    const { series } = useChartLayout()
    const { insightProps } = useValues(insightLogic)
    const { goalLines } = useValues(funnelDataLogic(insightProps))

    return <ReferenceLines lines={goalLinesToReferenceLines(goalLines, series)} />
}
