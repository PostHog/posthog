import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { DateRange } from '~/queries/schema/schema-general'

export interface BreakdownPreset {
    property: string
    title: string
}

export const POSTHOG_BREAKDOWN_NULL_VALUE = '$$_posthog_breakdown_null_$$'

export const ERROR_TRACKING_BREAKDOWNS_DATA_COLLECTION_NODE_ID = 'error-tracking-breakdowns'

export const LIMIT_ITEMS = 3

export const BREAKDOWN_PRESETS: BreakdownPreset[] = [
    { property: '$browser', title: 'Browser' },
    { property: '$device_type', title: 'Device Type' },
    { property: '$os', title: 'Operating System' },
    { property: '$pathname', title: 'Path' },
    { property: '$user_id', title: 'User ID' },
    { property: '$ip', title: 'IP Address' },
]

export const DEFAULT_DATE_RANGE: DateRange = { date_from: '-7d', date_to: null }

export const DEFAULT_TEST_ACCOUNT = false

export const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
]
