import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import { PathsV2AnchorType } from '~/queries/schema/schema-general'
import { EditorFilterProps, PropertyFilterType, PropertyOperator } from '~/types'

import { JourneyShape } from './anchorUtils'
import { journeysDataLogic } from './journeysDataLogic'

const SHAPE_OPTIONS: { value: JourneyShape; label: string; 'data-attr': string }[] = [
    { value: 'open', label: 'Open', 'data-attr': 'journeys-shape-open' },
    { value: PathsV2AnchorType.Start, label: 'Starts at', 'data-attr': 'journeys-shape-start' },
    { value: PathsV2AnchorType.End, label: 'Ends at', 'data-attr': 'journeys-shape-end' },
]

export function JourneysShapePicker({ insightProps }: EditorFilterProps): JSX.Element {
    const { journeyShape, anchorEvent, anchorLabel, anchorSource, stepSources } = useValues(
        journeysDataLogic(insightProps)
    )
    const { setJourneyShape, setAnchorEvent, setAnchorLabel } = useActions(journeysDataLogic(insightProps))

    return (
        <div className="flex flex-col gap-2">
            <LemonSegmentedButton
                size="small"
                value={journeyShape}
                onChange={setJourneyShape}
                options={SHAPE_OPTIONS}
            />
            {journeyShape !== 'open' && (
                <div className="flex items-center gap-2">
                    {/* With a single step source the anchor's event is implied, so only offer a
                        choice when there is one to make. */}
                    {stepSources.length > 1 && (
                        <LemonSelect
                            size="small"
                            placeholder="Select event"
                            value={anchorEvent}
                            onChange={(event) => event && setAnchorEvent(event)}
                            options={stepSources.map((source) => ({
                                value: source.event,
                                label: (
                                    <PropertyKeyInfo
                                        value={source.event}
                                        type={TaxonomicFilterGroupType.Events}
                                        disablePopover
                                    />
                                ),
                            }))}
                            data-attr="journeys-anchor-event"
                        />
                    )}
                    {anchorSource?.namingProperty && (
                        <div className="grow" data-attr="journeys-anchor-label">
                            <PropertyValue
                                propertyKey={anchorSource.namingProperty}
                                type={PropertyFilterType.Event}
                                operator={PropertyOperator.Exact}
                                eventNames={[anchorSource.event]}
                                value={anchorLabel}
                                onSet={(label: string | undefined) => setAnchorLabel(label ?? null)}
                                placeholder={
                                    journeyShape === PathsV2AnchorType.Start
                                        ? 'Where journeys start'
                                        : 'Where journeys end'
                                }
                                forceSingleSelect
                            />
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
