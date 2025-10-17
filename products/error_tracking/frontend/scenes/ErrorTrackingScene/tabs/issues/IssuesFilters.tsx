import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'

export function IssuesFilters(): JSX.Element {
    return (
        <ErrorFilters.Root>
            <div className="flex gap-2 justify-between flex-wrap">
                <div className="flex gap-2">
                    <ErrorFilters.DateRange />
                    <ErrorFilters.Status />
                    <ErrorFilters.Assignee />
                </div>
                <ErrorFilters.InternalAccounts />
            </div>
            <ErrorFilters.FilterGroup />
        </ErrorFilters.Root>
    )
}
