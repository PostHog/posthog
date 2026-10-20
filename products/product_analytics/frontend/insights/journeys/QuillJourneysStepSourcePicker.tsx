import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { Button, ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { QuillIconButton } from 'lib/components/QuillIconButton/QuillIconButton'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { EditorFilterProps } from '~/types'

import { EventName } from 'products/actions/frontend/components/EventName'

import { MAX_STEP_SOURCES } from './editorBounds'
import { journeysDataLogic } from './journeysDataLogic'
import { STEP_SOURCE_PRESETS, StepSourcePreset, presetForStepSources } from './stepSourcePresets'

export function QuillJourneysStepSourcePicker({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter, stepSources, anchor } = useValues(journeysDataLogic(insightProps))
    const { setStepSources, setStepSourceEvent, setStepSourceNamingProperty, addStepSource, removeStepSource } =
        useActions(journeysDataLogic(insightProps))

    // A source without an event is not a valid query, so a new source stays a pending row until its event is picked
    const [showPendingSource, setShowPendingSource] = useState(false)

    const preset = presetForStepSources(pathsV2Filter?.stepSources ?? undefined)
    const addDisabledReason =
        stepSources.length >= MAX_STEP_SOURCES ? `A journey supports up to ${MAX_STEP_SOURCES} step sources` : undefined

    return (
        <div className="flex flex-col gap-2">
            <ToggleGroup
                aria-label="Step sources"
                value={preset ? [preset.key] : []}
                onValueChange={(value: string[]) => {
                    if (value[0]) {
                        setStepSources(STEP_SOURCE_PRESETS[value[0] as StepSourcePreset['key']].stepSources)
                        setShowPendingSource(false)
                    }
                }}
            >
                {Object.values(STEP_SOURCE_PRESETS).map(({ key, label }) => (
                    <ToggleGroupItem key={key} value={key} data-attr={`journeys-step-source-${key}`}>
                        {label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            {stepSources.map((source, index) => {
                const isAnchorSource = anchor?.item.event === source.event
                const eventPicker = (
                    <EventName
                        value={source.event}
                        onChange={(event) => setStepSourceEvent(index, event)}
                        disabled={isAnchorSource}
                    />
                )
                return (
                    <div key={index} className="flex items-center gap-2">
                        {isAnchorSource ? (
                            <Tooltip>
                                <TooltipTrigger render={<span className="inline-flex" />}>{eventPicker}</TooltipTrigger>
                                <TooltipContent>This source is the journey's anchor</TooltipContent>
                            </Tooltip>
                        ) : (
                            <span className="inline-flex">{eventPicker}</span>
                        )}
                        <span className="shrink-0 text-muted-foreground">named by</span>
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
                            data-attr={`journeys-step-source-naming-property-${index}`}
                        />
                        <QuillIconButton
                            label="Remove step source"
                            icon={<IconTrash />}
                            onClick={() => removeStepSource(index)}
                            disabledReason={
                                stepSources.length === 1
                                    ? 'At least one step source is required'
                                    : isAnchorSource
                                      ? "This source is the journey's anchor"
                                      : undefined
                            }
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
                    <QuillIconButton
                        label="Remove step source"
                        icon={<IconTrash />}
                        onClick={() => setShowPendingSource(false)}
                        data-attr="journeys-step-source-remove-new"
                    />
                </div>
            ) : (
                <div>
                    <Tooltip disabled={!addDisabledReason}>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="outline"
                                    onClick={() => setShowPendingSource(true)}
                                    disabled={!!addDisabledReason}
                                    data-attr="journeys-step-source-add"
                                />
                            }
                        >
                            <IconPlus />
                            Add step source
                        </TooltipTrigger>
                        <TooltipContent>{addDisabledReason}</TooltipContent>
                    </Tooltip>
                </div>
            )}
        </div>
    )
}
