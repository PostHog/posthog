import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { PropertyFilterType } from '~/types'

import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../errorTrackingSceneLogic'

const QUICK_FILTER_CONTEXT = QuickFilterContext.ErrorTrackingIssueFilters

const INSIGHTS_TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.ErrorTrackingProperties,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.HogQLExpression,
]

export function InsightsFilters({ reload }: { reload?: React.ReactNode }): JSX.Element {
    return (
        <ErrorFilters.Root>
            <ErrorFilters.SearchBar>
                {reload && (
                    <>
                        <div className="flex items-stretch rounded-l-full overflow-hidden">{reload}</div>
                        <ErrorFilters.SearchBarDivider />
                    </>
                )}
                <div className="flex items-stretch overflow-hidden">
                    <ErrorFilters.DateRange type="tertiary" />
                </div>
                <ErrorFilters.SearchBarDivider />
                <div className="flex items-stretch overflow-hidden">
                    <ErrorFilters.SettingsMenu
                        quickFilterContext={QUICK_FILTER_CONTEXT}
                        logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                        showIssueFilters={false}
                    />
                </div>
                <ErrorFilters.SearchBarDivider />
                <div className="flex-1 rounded-r-full overflow-hidden">
                    <ErrorFilters.FilterGroup
                        taxonomicGroupTypes={INSIGHTS_TAXONOMIC_GROUP_TYPES}
                        excludeFilterTypes={[PropertyFilterType.ErrorTrackingIssue]}
                        quickFilterContext={QUICK_FILTER_CONTEXT}
                        logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                        showIssueFilters={false}
                    />
                </div>
            </ErrorFilters.SearchBar>
        </ErrorFilters.Root>
    )
}
