import { HoqQLPropertyInfo } from 'lib/components/HoqQLPropertyInfo'
import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { BreakdownType } from '~/types'

export interface BreakdownTagLabelProps {
    propertyName: string | number
    breakdownType: BreakdownType | null | undefined
    disablePropertyInfo?: boolean
}

export function BreakdownTagLabel({
    propertyName,
    breakdownType,
    disablePropertyInfo,
}: BreakdownTagLabelProps): JSX.Element {
    return breakdownType === 'hogql' ? (
        <HoqQLPropertyInfo value={propertyName as string} />
    ) : (
        <PropertyKeyInfo
            value={propertyName as string}
            disablePopover={disablePropertyInfo}
            type={
                breakdownType
                    ? PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[breakdownType]
                    : TaxonomicFilterGroupType.EventProperties
            }
        />
    )
}
