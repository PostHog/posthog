import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Separator } from 'lib/ui/quill'

import { PropertyFilterType } from '~/types'

import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'
import { ErrorTrackingQuickFilters } from 'products/error_tracking/frontend/components/IssueFilters/QuickFilters'

const INSIGHTS_TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.ErrorTrackingProperties,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.HogQLExpression,
]

export function InsightsFilters(): JSX.Element {
    return (
        <ErrorFilters.Root>
            <div className="flex w-full flex-wrap items-center gap-1">
                <ErrorFilters.DateRange />
                <Separator orientation="vertical" className="h-6" />
                <ErrorTrackingQuickFilters />
                <ErrorFilters.FilterGroup
                    taxonomicGroupTypes={INSIGHTS_TAXONOMIC_GROUP_TYPES}
                    excludeFilterTypes={[PropertyFilterType.ErrorTrackingIssue]}
                    activeFiltersInline
                />
                <div className="ml-auto shrink-0">
                    <ErrorFilters.InternalAccounts />
                </div>
            </div>
        </ErrorFilters.Root>
    )
}
