import { useActions, useValues } from 'kea'

import { IconPinFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { MAX_PINNED_PROPERTIES, observationPinnedPropertiesLogic } from './observationPinnedPropertiesLogic'

/** The popover contents behind the pinned-properties gear on the observation page. */
export function ObservationPinnedPropertiesPicker(): JSX.Element {
    const { pinnedProperties } = useValues(observationPinnedPropertiesLogic)
    const { togglePropertyPin, resetPinnedProperties } = useActions(observationPinnedPropertiesLogic)
    const atLimit = pinnedProperties.length >= MAX_PINNED_PROPERTIES

    return (
        <div className="w-80 max-w-full">
            <div className="flex items-center gap-2 px-3 py-2 border-b">
                <IconPinFilled className="text-muted" />
                <span className="text-sm font-semibold">Pinned session properties</span>
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
                taxonomicGroupTypes={[TaxonomicFilterGroupType.SessionProperties]}
                selectedProperties={{ [TaxonomicFilterGroupType.SessionProperties]: pinnedProperties }}
                onChange={(_, propertyKey) => {
                    const key = String(propertyKey)
                    if (!atLimit || pinnedProperties.includes(key)) {
                        togglePropertyPin(key)
                    }
                }}
            />
        </div>
    )
}
