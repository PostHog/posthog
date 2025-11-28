import { LemonDivider } from '@posthog/lemon-ui'

import { QuickFiltersSection } from 'lib/components/QuickFilters/QuickFiltersSection'

import { QuickFilterContext } from '~/queries/schema/schema-general'

import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'

export function IssuesFilters(): JSX.Element {
    return (
        <ErrorFilters.Root>
            <div className="flex gap-2 flex-wrap">
                <ErrorFilters.DateRange />
                <ErrorFilters.Status />
                <ErrorFilters.Assignee />
                <LemonDivider vertical />
                <QuickFiltersSection context={QuickFilterContext.ErrorTrackingIssueFilters} />
            </div>
            <div className="flex gap-2 items-start">
                <div className="flex-1">
                    <ErrorFilters.FilterGroup />
                </div>
                <ErrorFilters.InternalAccounts />
            </div>
        </ErrorFilters.Root>
    )
}
