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
