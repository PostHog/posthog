import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { QuillDisplayOptionSelect } from '~/queries/nodes/InsightViz/QuillDisplayOptionSelect'
import { RetentionDashboardDisplayType } from '~/types'

const OPTIONS: { value: RetentionDashboardDisplayType; label: string }[] = [
    { value: RetentionDashboardDisplayType.TableOnly, label: 'Show table only' },
    { value: RetentionDashboardDisplayType.GraphOnly, label: 'Show graph only' },
    { value: RetentionDashboardDisplayType.All, label: 'Show both' },
]

export function RetentionDashboardDisplayPicker(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const displayType = retentionFilter?.dashboardDisplay || RetentionDashboardDisplayType.TableOnly
    const onDisplayChange = (value: RetentionDashboardDisplayType): void => {
        updateInsightFilter({ dashboardDisplay: value })
    }

    if (!canEditInsight) {
        return null
    }

    if (todayRailNav) {
        return <QuillDisplayOptionSelect value={displayType} options={OPTIONS} onChange={onDisplayChange} fullWidth />
    }

    return (
        <LemonSelect
            className="pb-2 px-2"
            value={displayType}
            onChange={onDisplayChange}
            options={OPTIONS}
            size="small"
            fullWidth
        />
    )
}
