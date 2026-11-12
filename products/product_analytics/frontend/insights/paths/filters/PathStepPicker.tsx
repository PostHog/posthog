import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { DEFAULT_STEP_LIMIT } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'
import { pathsDataLogic } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'
import { QuillToolbarSelect } from 'products/product_analytics/frontend/insights/shared/QuillToolbarSelect'

interface StepOption {
    label: string
    value: number
}

export function PathStepPicker(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const { stepLimit } = pathsFilter || {}

    const MIN = 2,
        MAX = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) ? 20 : 5

    const options: StepOption[] = Array.from(Array.from(Array.from(Array(MAX + 1).keys()).slice(MIN)), (v) => ({
        label: `${v} Steps`,
        value: v,
    }))

    const selectStepLimit = (count: number): void => updateInsightFilter({ stepLimit: count })

    return todayRailNav ? (
        <QuillToolbarSelect
            value={stepLimit || DEFAULT_STEP_LIMIT}
            onChange={selectStepLimit}
            options={options}
            disabledReason={editingDisabledReason}
        />
    ) : (
        <LemonSelect
            size="small"
            value={stepLimit || DEFAULT_STEP_LIMIT}
            onChange={selectStepLimit}
            options={options}
            disabledReason={editingDisabledReason}
        />
    )
}
