import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { CustomChartButton } from './CustomChartButton'

export function InsightCustomChartButton(): JSX.Element | null {
    const { insightProps, insight, editingDisabledReason } = useValues(insightLogic)
    const { customChart, customChartData } = useValues(insightVizDataLogic(insightProps))
    const { updateCustomChart } = useActions(insightVizDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.CUSTOM_CHART_INSIGHTS]) {
        return null
    }

    return (
        <CustomChartButton
            logicKey={keyForInsightLogicProps('new')(insightProps)}
            customChart={customChart}
            insightName={insight.name || insight.derived_name || ''}
            data={customChartData}
            onChange={updateCustomChart}
            disabledReason={editingDisabledReason}
        />
    )
}
