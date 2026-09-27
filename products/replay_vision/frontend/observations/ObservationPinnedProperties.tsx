import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { Popover } from 'lib/lemon-ui/Popover'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { Fact, FactList } from './FactList'
import {
    PINNED_PROPERTY_GROUPS,
    PinnedProperty,
    observationPinnedPropertiesLogic,
} from './observationPinnedPropertiesLogic'
import { ObservationPinnedPropertiesPicker } from './ObservationPinnedPropertiesPicker'
import { observationSessionPropertiesLogic, pinnedPropertyId } from './observationSessionPropertiesLogic'

function propertyLabel(property: PinnedProperty): string {
    return getCoreFilterDefinition(property.key, PINNED_PROPERTY_GROUPS[property.type])?.label ?? property.key
}

function PinnedPropertyValue({ property, value }: { property: PinnedProperty; value: string | null }): JSX.Element {
    if (!value) {
        return <span className="text-muted">—</span>
    }
    const isUrl = value.startsWith('http://') || value.startsWith('https://')
    return (
        <Tooltip title={value}>
            <span className="flex items-center gap-1 min-w-0">
                <PropertyIcon property={property.key} value={value} />
                {isUrl ? (
                    <Link to={value} target="_blank" className="truncate">
                        {value}
                    </Link>
                ) : (
                    <CopyToClipboardInline
                        explicitValue={value}
                        description={propertyLabel(property)}
                        iconSize="xsmall"
                        className="min-w-0"
                    >
                        <span className="truncate">{value}</span>
                    </CopyToClipboardInline>
                )}
            </span>
        </Tooltip>
    )
}

/**
 * A fixed strip of properties for the observed session. It sits in the same place on every
 * observation so paging through a scanner's results with prev/next reads as a comparison.
 */
export function ObservationPinnedProperties({ sessionId }: { sessionId: string }): JSX.Element {
    const [pickerOpen, setPickerOpen] = useState(false)
    const { pinnedProperties, queryablePinnedProperties } = useValues(observationPinnedPropertiesLogic)
    const { resetPinnedProperties } = useActions(observationPinnedPropertiesLogic)
    const { sessionProperties, sessionPropertiesLoading } = useValues(observationSessionPropertiesLogic({ sessionId }))

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">Pinned properties</span>
                <Popover
                    visible={pickerOpen}
                    onClickOutside={() => setPickerOpen(false)}
                    overlay={<ObservationPinnedPropertiesPicker />}
                    placement="bottom-end"
                >
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => setPickerOpen(!pickerOpen)}
                        data-attr="vision-observation-pin-properties"
                    >
                        Edit
                    </LemonButton>
                </Popover>
            </div>
            {pinnedProperties.length === 0 ? (
                <p className="text-sm text-muted m-0">
                    Nothing pinned. Use Edit to pick properties that show on every observation.
                </p>
            ) : queryablePinnedProperties.length === 0 ? (
                <p className="text-sm text-muted m-0">
                    None of the pinned session properties exist in this project.{' '}
                    <Link onClick={resetPinnedProperties}>Reset to the defaults</Link>.
                </p>
            ) : sessionPropertiesLoading ? (
                <LemonSkeleton.Row repeat={2} className="h-5" />
            ) : (
                <FactList>
                    {queryablePinnedProperties.map((property) => (
                        <Fact key={pinnedPropertyId(property)} label={propertyLabel(property)}>
                            <PinnedPropertyValue
                                property={property}
                                value={sessionProperties?.[pinnedPropertyId(property)] ?? null}
                            />
                        </Fact>
                    ))}
                </FactList>
            )}
        </div>
    )
}
