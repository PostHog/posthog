import { LemonDivider } from '@posthog/lemon-ui'

import { QuickFiltersSection } from 'lib/components/QuickFilters/QuickFiltersSection'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { PropertyFilterType } from '~/types'

import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../errorTrackingSceneLogic'

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
            <div className="flex gap-2 flex-wrap">
                <ErrorFilters.DateRange />
                <LemonDivider vertical />
                <QuickFiltersSection
                    context={QuickFilterContext.ErrorTrackingIssueFilters}
                    logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                />
            </div>
            <div className="flex gap-2 items-start">
                <div className="flex-1">
                    <ErrorFilters.FilterGroup
                        taxonomicGroupTypes={INSIGHTS_TAXONOMIC_GROUP_TYPES}
                        excludeFilterTypes={[PropertyFilterType.ErrorTrackingIssue]}
                    />
                </div>
                <ErrorFilters.InternalAccounts />
            </div>
        </ErrorFilters.Root>
    )
}
