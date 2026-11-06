import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'
import { ErrorTrackingQuickFilters } from 'products/error_tracking/frontend/components/IssueFilters/QuickFilters'
import {
    IssueSortButton,
    ReloadIssuesButton,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/IssueQueryOptions'

export function IssuesFilters(): JSX.Element {
    return (
        <ErrorFilters.Root>
            <div className="flex flex-col gap-2">
                <div className="flex items-start gap-2">
                    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                        <ReloadIssuesButton />
                        <ErrorFilters.DateRange />
                        <ErrorFilters.Status />
                        <ErrorFilters.Severity />
                        <ErrorFilters.Assignee />
                        <ErrorFilters.InternalAccounts />
                    </div>
                    <div className="ml-auto flex shrink-0 items-center gap-2">
                        <ErrorTrackingQuickFilters />
                    </div>
                </div>
                <div className="flex w-full flex-wrap items-center gap-2">
                    <ErrorFilters.Search />
                    <ErrorFilters.FilterGroup activeFiltersInline />
                    <div className="ml-auto shrink-0">
                        <IssueSortButton />
                    </div>
                </div>
            </div>
        </ErrorFilters.Root>
    )
}
