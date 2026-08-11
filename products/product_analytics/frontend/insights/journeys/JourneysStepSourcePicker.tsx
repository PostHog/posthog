import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { EditorFilterProps } from '~/types'

import { EventName } from 'products/actions/frontend/components/EventName'

import { MAX_STEP_SOURCES } from './editorBounds'
import { journeysDataLogic } from './journeysDataLogic'
import { STEP_SOURCE_PRESETS, StepSourcePreset, presetForStepSources } from './stepSourcePresets'

const PRESET_OPTIONS = Object.values(STEP_SOURCE_PRESETS).map(({ key, label }) => ({
    value: key,
    label,
    'data-attr': `journeys-step-source-${key}`,
}))

export function JourneysStepSourcePicker({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter, stepSources, anchor } = useValues(journeysDataLogic(insightProps))
    const { setStepSources, setStepSourceEvent, setStepSourceNamingProperty, addStepSource, removeStepSource } =
        useActions(journeysDataLogic(insightProps))

    // A new source only enters the query once its event is picked, as a source without an event is
    // not a valid query. Until then it exists as this pending row.
    const [showPendingSource, setShowPendingSource] = useState(false)

    const preset = presetForStepSources(pathsV2Filter?.stepSources ?? undefined)

    return (
        <div className="flex flex-col gap-2">
            <LemonSegmentedButton
                size="small"
                value={preset?.key}
                onChange={(key: StepSourcePreset['key']) => {
                    setStepSources(STEP_SOURCE_PRESETS[key].stepSources)
                    setShowPendingSource(false)
                }}
                options={PRESET_OPTIONS}
            />
            {stepSources.map((source, index) => {
                const isAnchorSource = anchor?.item.event === source.event
                return (
                    <div key={index} className="flex items-center gap-2">
                        <Tooltip title={isAnchorSource ? "This source is the journey's anchor" : undefined}>
                            <span className="inline-flex">
                                <EventName
                                    value={source.event}
                                    onChange={(event) => setStepSourceEvent(index, event)}
                                    disabled={isAnchorSource}
                                />
                            </span>
                        </Tooltip>
                        <span className="text-secondary shrink-0">named by</span>
                        <TaxonomicStringPopover
                            groupType={TaxonomicFilterGroupType.EventProperties}
                            value={source.namingProperty ?? undefined}
                            onChange={(namingProperty) => setStepSourceNamingProperty(index, namingProperty)}
                            renderValue={(namingProperty) => (
                                <PropertyKeyInfo
                                    value={namingProperty}
                                    type={TaxonomicFilterGroupType.EventProperties}
                                    disablePopover
                                />
                            )}
                            eventNames={[source.event]}
                            placeholder="Event name only"
                            allowClear
                            size="small"
                            type="secondary"
                            data-attr={`journeys-step-source-naming-property-${index}`}
                        />
                        <LemonButton
                            icon={<IconTrash />}
                            size="small"
                            onClick={() => removeStepSource(index)}
                            disabledReason={
                                stepSources.length === 1
                                    ? 'At least one step source is required'
                                    : isAnchorSource
                                      ? "This source is the journey's anchor"
                                      : undefined
                            }
                            tooltip="Remove step source"
                            data-attr={`journeys-step-source-remove-${index}`}
                        />
                    </div>
                )
            })}
            {showPendingSource ? (
                <div className="flex items-center gap-2">
                    <EventName
                        value=""
                        onChange={(event) => {
                            addStepSource(event)
                            setShowPendingSource(false)
                        }}
                        placeholder="Select event"
                    />
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        onClick={() => setShowPendingSource(false)}
                        tooltip="Remove step source"
                        data-attr="journeys-step-source-remove-new"
                    />
                </div>
            ) : (
                <div>
                    <LemonButton
                        icon={<IconPlusSmall />}
                        size="small"
                        type="secondary"
                        onClick={() => setShowPendingSource(true)}
                        disabledReason={
                            stepSources.length >= MAX_STEP_SOURCES
                                ? `A journey supports up to ${MAX_STEP_SOURCES} step sources`
                                : undefined
                        }
                        data-attr="journeys-step-source-add"
                    >
                        Add step source
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
