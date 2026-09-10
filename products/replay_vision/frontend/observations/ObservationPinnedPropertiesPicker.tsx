import { useActions, useValues } from 'kea'

import { IconPinFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { SelectedProperties, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import {
    MAX_PINNED_PROPERTIES,
    PINNED_PROPERTY_GROUPS,
    observationPinnedPropertiesLogic,
    pinnedPropertyTypeForGroup,
} from './observationPinnedPropertiesLogic'

const PICKER_GROUPS = [
    TaxonomicFilterGroupType.SessionProperties,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
]

/** The popover contents behind the pinned-properties gear on the observation page. */
export function ObservationPinnedPropertiesPicker(): JSX.Element {
    const { pinnedProperties } = useValues(observationPinnedPropertiesLogic)
    const { togglePropertyPin, resetPinnedProperties } = useActions(observationPinnedPropertiesLogic)
    const atLimit = pinnedProperties.length >= MAX_PINNED_PROPERTIES

    // Each group only marks its own pins, so the same key pinned as an event property doesn't
    // read as pinned under person properties too.
    const selectedProperties = Object.fromEntries(
        Object.entries(PINNED_PROPERTY_GROUPS).map(([type, group]) => [
            group,
            pinnedProperties.filter((property) => property.type === type).map((property) => property.key),
        ])
    ) as SelectedProperties

    return (
        <div>
            <div className="flex items-center gap-2 px-3 py-2 border-b">
                <IconPinFilled className="text-muted" />
                <span className="text-sm font-semibold">Pinned properties</span>
                <LemonButton size="xsmall" type="tertiary" className="ml-auto" onClick={resetPinnedProperties}>
                    Reset
                </LemonButton>
            </div>
            {atLimit && (
                <p className="text-xs text-muted m-0 px-3 py-2">
                    Unpin one to add another. {MAX_PINNED_PROPERTIES} is the most that stays scannable.
                </p>
            )}
            <TaxonomicFilter
                taxonomicFilterLogicKey="replay-vision-pinned-properties"
                taxonomicGroupTypes={PICKER_GROUPS}
                selectedProperties={selectedProperties}
                onChange={(group, propertyKey) => {
                    const type = pinnedPropertyTypeForGroup(group.type)
                    if (!type) {
                        return
                    }
                    const key = String(propertyKey)
                    const isPinned = pinnedProperties.some((property) => property.key === key && property.type === type)
                    if (!atLimit || isPinned) {
                        togglePropertyPin(key, type)
                    }
                }}
            />
        </div>
    )
}
