import { useValues } from 'kea'

import { ReferenceLines } from '@posthog/quill-charts'

import type { InsightLogicProps } from '~/types'

import { insightAlertsLogic } from 'products/alerts/frontend/logic/insightAlertsLogic'

import { alertThresholdsToReferenceLines } from '../../trends/shared/goalLinesAdapter'

export function FunnelAlertThresholdLines({
    insightId,
    insightProps,
    axisOrientation,
}: {
    insightId: number
    insightProps: InsightLogicProps
    axisOrientation?: 'vertical' | 'horizontal'
}): JSX.Element | null {
    const { allAlertThresholdLines } = useValues(insightAlertsLogic({ insightId, insightLogicProps: insightProps }))
    const lines = alertThresholdsToReferenceLines(allAlertThresholdLines, axisOrientation)
    return lines.length ? <ReferenceLines lines={lines} /> : null
}
