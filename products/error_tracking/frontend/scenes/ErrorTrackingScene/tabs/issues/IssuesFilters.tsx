import { Separator } from 'lib/ui/quill'

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
                <div className="flex flex-wrap items-center gap-1">
                    <div className="flex shrink-0 items-center gap-1">
                        <ReloadIssuesButton />
                        <ErrorFilters.DateRange />
                    </div>
                    <ErrorFilters.Status />
                    <ErrorFilters.Assignee />
                    <Separator orientation="vertical" className="h-6" />
                    <ErrorTrackingQuickFilters />
                    <div className="ml-auto shrink-0">
                        <ErrorFilters.InternalAccounts />
                    </div>
                </div>
                <div className="flex w-full flex-wrap items-center gap-1">
                    <ErrorFilters.FilterGroup activeFiltersInline />
                    <div className="ml-auto shrink-0">
                        <IssueSortButton />
                    </div>
                </div>
            </div>
        </ErrorFilters.Root>
    )
}
