import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'
import type { LemonSegmentedButtonOption } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { logsServicesLogic, ServicesViewMode } from './logsServicesLogic'
import { ServicesList } from './ServicesList'

const DATE_OPTIONS = [
    { value: '-1h', label: 'Last hour' },
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
    { value: '-30d', label: 'Last 30 days' },
]

const VIEW_MODE_OPTIONS: LemonSegmentedButtonOption<ServicesViewMode>[] = [
    { value: 'list', label: 'List', 'data-attr': 'logs-services-view-mode-list' },
    { value: 'grid', label: 'Grid', 'data-attr': 'logs-services-view-mode-grid' },
]

function ServicesGrid(): JSX.Element {
    return (
        <div className="p-4 text-center text-muted">
            Grid view is not built yet. Switch to List to see your services.
        </div>
    )
}

export function LogsServicesV2(): JSX.Element {
    const { sortedServices, services, totalServices, servicesDataLoading, searchTerm, dateFrom, viewMode } =
        useValues(logsServicesLogic)
    const { setDateFrom, setSearchTerm, setViewMode } = useActions(logsServicesLogic)

    return (
        <div className="flex flex-col gap-2 py-2 flex-1 min-h-0">
            {totalServices > services.length && (
                <LemonBanner type="info" className="mb-0">
                    Showing the top {humanFriendlyNumber(services.length)} of {humanFriendlyNumber(totalServices)}{' '}
                    {searchTerm ? 'matching services' : 'services'} by volume.{' '}
                    {searchTerm ? 'Refine your search to see the rest.' : 'Use search to find the rest.'}
                </LemonBanner>
            )}
            <div className="flex items-center justify-between gap-2">
                <LemonSegmentedButton
                    size="small"
                    value={viewMode}
                    onChange={setViewMode}
                    options={VIEW_MODE_OPTIONS}
                />
                <div className="flex items-center gap-2">
                    <LemonInput
                        size="small"
                        type="search"
                        placeholder="Search services"
                        value={searchTerm}
                        onChange={setSearchTerm}
                    />
                    <LemonSelect
                        size="small"
                        value={dateFrom}
                        onChange={(value) => value && setDateFrom(value)}
                        options={DATE_OPTIONS}
                    />
                </div>
            </div>
            {/* The scene container is a fixed height and does not scroll, so this region has to. */}
            <div className="flex-1 min-h-0 overflow-y-auto" data-attr="logs-services-v2">
                {viewMode === 'grid' ? (
                    <ServicesGrid />
                ) : (
                    <ServicesList services={sortedServices} loading={servicesDataLoading} searchTerm={searchTerm} />
                )}
            </div>
        </div>
    )
}
