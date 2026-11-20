import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInputSelect, type LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect'

import { anomaliesDashboardPickerLogic } from './anomaliesDashboardPickerLogic'
import { anomaliesTabLogic } from './anomaliesTabLogic'

const ALL_DASHBOARDS = 'all'

export function AnomaliesDashboardPicker(): JSX.Element {
    const { filters } = useValues(anomaliesTabLogic)
    const { setFilters } = useActions(anomaliesTabLogic)
    const { dashboardOptions, dashboardOptionsLoading, dashboardOptionsFailed, pickedDashboard, search } =
        useValues(anomaliesDashboardPickerLogic)
    const { ensureOptionsLoaded, loadOptions, pickDashboard, setSearch } = useActions(anomaliesDashboardPickerLogic)

    const options = useMemo((): LemonInputSelectOption[] => {
        const names = new Map<number, string>()
        if (pickedDashboard) {
            names.set(pickedDashboard.id, pickedDashboard.name)
        }
        for (const dashboard of dashboardOptions) {
            names.set(dashboard.id, dashboard.name || 'Untitled dashboard')
        }
        // A search leaves out the option to clear the filter, so a search with no match shows the empty state.
        return [
            ...(search.trim() ? [] : [{ key: ALL_DASHBOARDS, label: 'All dashboards' }]),
            ...Array.from(names, ([id, name]) => ({ key: String(id), label: name })),
        ]
    }, [dashboardOptions, pickedDashboard, search])

    return (
        <div className="w-56">
            <LemonInputSelect
                mode="single"
                size="small"
                placeholder="All dashboards"
                loading={dashboardOptionsLoading}
                disableFiltering
                value={filters.dashboardId != null ? [String(filters.dashboardId)] : []}
                options={options}
                title={
                    dashboardOptionsFailed ? (
                        <span className="flex items-center justify-between gap-2 font-normal">
                            <span className="text-danger">Couldn't load dashboards.</span>
                            <LemonButton size="xsmall" type="secondary" onClick={() => loadOptions()}>
                                Try again
                            </LemonButton>
                        </span>
                    ) : undefined
                }
                emptyStateComponent={
                    dashboardOptionsFailed ? (
                        <></>
                    ) : (
                        <p className="text-secondary italic p-1">
                            {search.trim() ? `No dashboards match "${search.trim()}"` : 'No dashboards in this project'}
                        </p>
                    )
                }
                onFocus={ensureOptionsLoaded}
                onInputChange={setSearch}
                onChange={([key]) => {
                    if (!key || key === ALL_DASHBOARDS) {
                        setFilters({ dashboardId: null })
                        return
                    }
                    const option = options.find((candidate) => candidate.key === key)
                    pickDashboard({ id: Number(key), name: option?.label ?? 'Untitled dashboard' })
                    setFilters({ dashboardId: Number(key) })
                }}
                data-attr="anomalies-tab-dashboard"
            />
        </div>
    )
}
