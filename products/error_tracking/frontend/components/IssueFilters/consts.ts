import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export const TAXONOMIC_FILTER_LOGIC_KEY = 'error-tracking'
export const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.ErrorTrackingProperties,
    TaxonomicFilterGroupType.ErrorTrackingIssues,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.HogQLExpression,
]

/** For surfaces scoped to events/properties where issue filters make no sense (insights, issue detail). */
export const NON_ISSUE_TAXONOMIC_GROUP_TYPES = TAXONOMIC_GROUP_TYPES.filter(
    (type) => type !== TaxonomicFilterGroupType.ErrorTrackingIssues
)
