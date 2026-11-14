import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import {
    Button,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip as QuillTooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import {
    STEP_SOURCE_PRESETS,
    StepSourcePreset,
    presetForStepSources,
} from '~/queries/nodes/InsightQuery/stepSourcePresets'
import { EditorFilterProps } from '~/types'

import { EventName } from 'products/actions/frontend/components/EventName'

import { MAX_STEP_SOURCES } from './editorBounds'
import { journeysDataLogic } from './journeysDataLogic'

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
    const quillSurface = useQuillSurface()

    const preset = presetForStepSources(pathsV2Filter?.stepSources ?? undefined)
    const onPresetChange = (key: StepSourcePreset['key']): void => {
        setStepSources(STEP_SOURCE_PRESETS[key].stepSources)
        setShowPendingSource(false)
    }
    const addDisabledReason =
        stepSources.length >= MAX_STEP_SOURCES ? `A journey supports up to ${MAX_STEP_SOURCES} step sources` : undefined

    return (
        <div className="flex flex-col gap-2">
            {quillSurface ? (
                <ToggleGroup
                    className="flex-wrap"
                    value={preset ? [preset.key] : []}
                    onValueChange={(next: string[]) => {
                        if (next.length > 0) {
                            onPresetChange(next[0] as StepSourcePreset['key'])
                        }
                    }}
                >
                    {PRESET_OPTIONS.map((option) => (
                        <ToggleGroupItem key={option.value} value={option.value} data-attr={option['data-attr']}>
                            {option.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            ) : (
                <LemonSegmentedButton
                    size="small"
                    value={preset?.key}
                    onChange={onPresetChange}
                    options={PRESET_OPTIONS}
                />
            )}
            {stepSources.map((source, index) => {
                const isAnchorSource = anchor?.item.event === source.event
                const anchorReason = isAnchorSource ? "This source is the journey's anchor" : undefined
                const removeDisabledReason =
                    stepSources.length === 1 ? 'At least one step source is required' : anchorReason
                const eventName = (
                    <EventName
                        value={source.event}
                        onChange={(event) => setStepSourceEvent(index, event)}
                        disabled={isAnchorSource}
                    />
                )
                return (
                    <div
                        key={index}
                        className={quillSurface ? 'flex flex-wrap items-center gap-2' : 'flex items-center gap-2'}
                    >
                        {quillSurface ? (
                            <QuillTooltip disabled={!anchorReason}>
                                <TooltipTrigger render={<span className="inline-flex min-w-0" />}>
                                    {eventName}
                                </TooltipTrigger>
                                {anchorReason && <TooltipContent>{anchorReason}</TooltipContent>}
                            </QuillTooltip>
                        ) : (
                            <Tooltip title={anchorReason}>
                                <span className="inline-flex">{eventName}</span>
                            </Tooltip>
                        )}
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
                        {quillSurface ? (
                            <Button
                                size="icon"
                                aria-label="Remove step source"
                                tooltip="Remove step source"
                                onClick={() => removeStepSource(index)}
                                disabledReason={removeDisabledReason}
                                data-attr={`journeys-step-source-remove-${index}`}
                            >
                                <IconTrash />
                            </Button>
                        ) : (
                            <LemonButton
                                icon={<IconTrash />}
                                size="small"
                                onClick={() => removeStepSource(index)}
                                disabledReason={removeDisabledReason}
                                tooltip="Remove step source"
                                data-attr={`journeys-step-source-remove-${index}`}
                            />
                        )}
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
                    {quillSurface ? (
                        <Button
                            size="icon"
                            aria-label="Remove step source"
                            tooltip="Remove step source"
                            onClick={() => setShowPendingSource(false)}
                            data-attr="journeys-step-source-remove-new"
                        >
                            <IconTrash />
                        </Button>
                    ) : (
                        <LemonButton
                            icon={<IconTrash />}
                            size="small"
                            onClick={() => setShowPendingSource(false)}
                            tooltip="Remove step source"
                            data-attr="journeys-step-source-remove-new"
                        />
                    )}
                </div>
            ) : (
                <div>
                    {quillSurface ? (
                        <Button
                            variant="outline"
                            onClick={() => setShowPendingSource(true)}
                            disabledReason={addDisabledReason}
                            data-attr="journeys-step-source-add"
                        >
                            <IconPlus />
                            Add step source
                        </Button>
                    ) : (
                        <LemonButton
                            icon={<IconPlusSmall />}
                            size="small"
                            type="secondary"
                            onClick={() => setShowPendingSource(true)}
                            disabledReason={addDisabledReason}
                            data-attr="journeys-step-source-add"
                        >
                            Add step source
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
}
