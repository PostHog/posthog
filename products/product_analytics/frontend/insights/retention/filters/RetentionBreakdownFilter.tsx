import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'

import { QuillToolbarSelect } from 'products/product_analytics/frontend/insights/shared/QuillToolbarSelect'

import { retentionLogic } from '../retentionLogic'

export function RetentionBreakdownFilter(): JSX.Element | null {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { breakdownValues, selectedBreakdownValue, breakdownDisplayNames } = useValues(retentionLogic(insightProps))
    const { setSelectedBreakdownValue } = useActions(retentionLogic(insightProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!breakdownValues || breakdownValues.length === 0) {
        return null
    }

    const options: { value: string | number | boolean | null; label: string }[] = [
        { value: null, label: 'All breakdown values' },
        ...breakdownValues.map((value) => ({
            value: value as string | number | boolean,
            label:
                breakdownDisplayNames[String(value ?? '')] ||
                (value === null || value === '' ? '(empty)' : String(value)),
        })),
    ]

    if (todayRailNav) {
        return (
            <QuillToolbarSelect
                value={selectedBreakdownValue}
                onChange={setSelectedBreakdownValue}
                options={options}
                placeholder="Select breakdown value"
                data-attr="retention-breakdown-filter"
                disabledReason={editingDisabledReason}
            />
        )
    }

    return (
        <LemonSelect
            value={selectedBreakdownValue}
            onChange={(value) => setSelectedBreakdownValue(value)}
            options={options as LemonSelectOption<string | number | boolean | null>[]}
            placeholder="Select breakdown value"
            size="small"
            data-attr="retention-breakdown-filter"
            disabledReason={editingDisabledReason}
        />
    )
}
