import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { PathsV2StepSource } from '~/queries/schema/schema-general'
import { EditorFilterProps } from '~/types'

import { journeysDataLogic } from './journeysDataLogic'
import { DEFAULT_STEP_SOURCES, STEP_SOURCE_PRESETS, StepSourcePreset, presetForStepSources } from './stepSourcePresets'

// Mirrors the @maxItems bound on PathsV2Filter.stepSources.
const MAX_STEP_SOURCES = 20

const PRESET_OPTIONS = Object.values(STEP_SOURCE_PRESETS).map(({ key, label }) => ({
    value: key,
    label,
    'data-attr': `journeys-step-source-${key}`,
}))

export function JourneysStepSourcePicker({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter } = useValues(journeysDataLogic(insightProps))
    const { updateInsightFilter } = useActions(journeysDataLogic(insightProps))

    // A new source only enters the query once its event is picked, as a source without an event is
    // not a valid query. Until then it exists as this pending row.
    const [showPendingSource, setShowPendingSource] = useState(false)

    const stepSources = pathsV2Filter?.stepSources ?? DEFAULT_STEP_SOURCES
    const preset = presetForStepSources(pathsV2Filter?.stepSources ?? undefined)

    useEffect(() => {
        setShowPendingSource(false)
    }, [pathsV2Filter?.stepSources])

    const setStepSources = (sources: PathsV2StepSource[]): void => {
        updateInsightFilter({ stepSources: sources })
    }

    const isDuplicateEvent = (event: string, index: number | null): boolean => {
        if (stepSources.some((source, i) => i !== index && source.event === event)) {
            lemonToast.info(`${event} is already a step source`)
            return true
        }
        return false
    }

    const setSourceEvent = (index: number, event: string): void => {
        if (isDuplicateEvent(event, index)) {
            return
        }
        setStepSources(stepSources.map((source, i) => (i === index ? { ...source, event } : source)))
    }

    const setSourceNamingProperty = (index: number, namingProperty: string): void => {
        setStepSources(
            stepSources.map((source, i) =>
                i === index ? { event: source.event, ...(namingProperty ? { namingProperty } : {}) } : source
            )
        )
    }

    const addSource = (event: string): void => {
        if (isDuplicateEvent(event, null)) {
            return
        }
        setStepSources([...stepSources, { event }])
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonSegmentedButton
                size="small"
                value={preset?.key}
                onChange={(key: StepSourcePreset['key']) =>
                    updateInsightFilter({ stepSources: STEP_SOURCE_PRESETS[key].stepSources })
                }
                options={PRESET_OPTIONS}
            />
            {stepSources.map((source, index) => (
                <div key={index} className="flex items-center gap-2">
                    <TaxonomicStringPopover
                        groupType={TaxonomicFilterGroupType.Events}
                        value={source.event}
                        onChange={(event) => setSourceEvent(index, event)}
                        renderValue={(event) => (
                            <PropertyKeyInfo value={event} type={TaxonomicFilterGroupType.Events} disablePopover />
                        )}
                        size="small"
                        type="secondary"
                        data-attr={`journeys-step-source-event-${index}`}
                    />
                    <span className="text-secondary shrink-0">named by</span>
                    <TaxonomicStringPopover
                        groupType={TaxonomicFilterGroupType.EventProperties}
                        value={source.namingProperty ?? undefined}
                        onChange={(namingProperty) => setSourceNamingProperty(index, namingProperty)}
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
                        onClick={() => setStepSources(stepSources.filter((_, i) => i !== index))}
                        disabledReason={stepSources.length === 1 ? 'At least one step source is required' : undefined}
                        tooltip="Remove step source"
                        data-attr={`journeys-step-source-remove-${index}`}
                    />
                </div>
            ))}
            {showPendingSource ? (
                <div className="flex items-center gap-2">
                    <TaxonomicStringPopover
                        groupType={TaxonomicFilterGroupType.Events}
                        onChange={(event) => addSource(event)}
                        placeholder="Select event"
                        size="small"
                        type="secondary"
                        data-attr="journeys-step-source-event-new"
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
