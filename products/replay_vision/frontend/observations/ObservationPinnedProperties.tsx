import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPin } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { CardHeader } from '../components/CardHeader'
import { LabeledRow } from '../components/LabeledRow'
import { observationPinnedPropertiesLogic } from './observationPinnedPropertiesLogic'
import { ObservationPinnedPropertiesPicker } from './ObservationPinnedPropertiesPicker'
import { observationSessionPropertiesLogic } from './observationSessionPropertiesLogic'

function propertyLabel(property: string): string {
    return getCoreFilterDefinition(property, TaxonomicFilterGroupType.SessionProperties)?.label ?? property
}

function PinnedPropertyValue({ property, value }: { property: string; value: string | null }): JSX.Element {
    if (!value) {
        return <span className="text-muted">—</span>
    }
    const isUrl = value.startsWith('http://') || value.startsWith('https://')
    return (
        <Tooltip title={value}>
            <span className="flex items-center gap-1 min-w-0">
                <PropertyIcon property={property} value={value} />
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
 * A fixed strip of session properties for the observed session. It sits in the same place on every
 * observation so paging through a scanner's results with prev/next reads as a comparison.
 */
export function ObservationPinnedProperties({ sessionId }: { sessionId: string }): JSX.Element {
    const [pickerOpen, setPickerOpen] = useState(false)
    const { pinnedProperties, queryablePinnedProperties } = useValues(observationPinnedPropertiesLogic)
    const { resetPinnedProperties } = useActions(observationPinnedPropertiesLogic)
    const { sessionProperties, sessionPropertiesLoading } = useValues(observationSessionPropertiesLogic({ sessionId }))

    return (
        <LemonCard className="p-4" hoverEffect={false}>
            <CardHeader
                icon={<IconPin />}
                title="Session properties"
                actions={
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
                            Edit pinned properties
                        </LemonButton>
                    </Popover>
                }
            />
            {pinnedProperties.length === 0 ? (
                <p className="text-sm text-muted m-0">
                    Pin the session properties you compare across results, like the referring domain or campaign source.
                </p>
            ) : queryablePinnedProperties.length === 0 ? (
                <p className="text-sm text-muted m-0">
                    None of the pinned properties exist on this project's sessions.{' '}
                    <Link onClick={resetPinnedProperties}>Reset to the defaults</Link>.
                </p>
            ) : sessionPropertiesLoading ? (
                <LemonSkeleton.Row repeat={2} className="h-5" />
            ) : (
                <div className="@container/pinned">
                    <div className="grid grid-cols-1 gap-x-6 gap-y-3 @md/pinned:grid-cols-2 @3xl/pinned:grid-cols-4">
                        {queryablePinnedProperties.map((property) => (
                            <div key={property} className="min-w-0">
                                <LabeledRow label={propertyLabel(property)}>
                                    <PinnedPropertyValue
                                        property={property}
                                        value={sessionProperties?.[property] ?? null}
                                    />
                                </LabeledRow>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </LemonCard>
    )
}
