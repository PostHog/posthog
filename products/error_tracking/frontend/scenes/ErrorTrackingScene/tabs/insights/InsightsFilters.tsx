import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'

export function InsightsFilters(): JSX.Element {
    return (
        <ErrorFilters.Root>
            <div className="flex gap-2 flex-wrap">
                <ErrorFilters.DateRange />
            </div>
            <div className="flex gap-2 items-start">
                <div className="flex-1 min-w-0">
                    <ErrorFilters.FilterGroup />
                </div>
                <ErrorFilters.InternalAccounts />
            </div>
        </ErrorFilters.Root>
    )
}
