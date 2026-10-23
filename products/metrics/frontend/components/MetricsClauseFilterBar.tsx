import { useActions, useValues } from 'kea'
import { type ReactNode, useState } from 'react'

import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { UniversalFiltersGroupValue } from '~/types'

import { METRIC_FILTER_OPERATOR_ALLOWLIST } from './metricsViewerLogic'

/** Filter chips + "Add filter" button for one clause row, mirroring the logs viewer's
 * applied-filters row: picking an attribute opens the chip for value selection, with
 * suggestions fed by the metrics attribute endpoints. Must render inside the row's
 * `UniversalFilters` provider. */
export function MetricsClauseFilterBar({
    disabledReason,
    addFilterTitle = 'Filter',
    addFilterType = 'secondary',
    addFilterDataAttr,
    addFilterTooltip,
    addFilterDisabledReason,
    actionsBeforeAddFilter,
}: {
    disabledReason: string | null
    addFilterTitle?: string
    addFilterType?: 'secondary' | 'tertiary'
    addFilterDataAttr?: string
    addFilterTooltip?: string | null
    /** Disables only the "Add filter" button. The chips stay editable, so the user can still remove them. */
    addFilterDisabledReason?: string | null
    /** Buttons shown after the chips and before the "Add filter" button. */
    actionsBeforeAddFilter?: ReactNode
}): JSX.Element {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState<boolean>(false)

    useOnMountEffect(() => setAllowInitiallyOpen(true))

    return (
        <div className="flex flex-wrap items-center gap-1">
            {filterGroup.values.map((filterOrGroup: UniversalFiltersGroupValue, index: number) =>
                // This UI only ever adds leaf filters, so nested groups can't occur here.
                isUniversalGroupFilterLike(filterOrGroup) ? null : (
                    <span
                        key={index}
                        title={disabledReason ?? undefined}
                        className={disabledReason ? 'pointer-events-none opacity-50' : undefined}
                    >
                        <UniversalFilters.Value
                            index={index}
                            filter={filterOrGroup}
                            onRemove={disabledReason ? undefined : () => removeGroupValue(index)}
                            onChange={(value) => {
                                if (!disabledReason) {
                                    replaceGroupValue(index, value)
                                }
                            }}
                            initiallyOpen={allowInitiallyOpen && !disabledReason}
                            operatorAllowlist={METRIC_FILTER_OPERATOR_ALLOWLIST}
                        />
                    </span>
                )
            )}
            {actionsBeforeAddFilter}
            <UniversalFilters.AddFilterButton
                size="small"
                type={addFilterType}
                title={addFilterTitle}
                disabledReason={disabledReason ?? addFilterDisabledReason}
                tooltip={addFilterTooltip}
                data-attr={addFilterDataAttr}
            />
        </div>
    )
}
