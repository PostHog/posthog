import { IconInfo } from '@posthog/icons'
import { LemonLabel, Tooltip } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { HogFlowEventFilters, WORKFLOW_OPERATOR_ALLOWLIST } from '../../filters/HogFlowFilters'
import { joinCohortMembershipEntry, splitCohortMembershipEntry } from './cohortMembershipEvent'
import { CohortMembershipEventPicker } from './CohortMembershipEventPicker'
import { HogFlowDuration, MAX_CONVERSION_WINDOW_FOR_DURATION_UNIT } from './HogFlowDuration'

// Structural shape of a workflow conversion goal, compatible with both the frontend HogFlow
// type and the generated HogFlowConversionApi type.
export interface ConversionGoalValue {
    window?: string | null
    filters?: any
    events?: { filters?: any; name?: string }[]
    bytecode?: unknown
}

export interface ConversionGoalEditorProps {
    conversion: ConversionGoalValue | null | undefined
    onChange: (conversion: ConversionGoalValue) => void
    /** Unique key for the filter pickers, so multiple editors on one page don't share state. */
    pageKey: string
}

const DEFAULT_CONVERSION_WINDOW = '90d'

export function ConversionGoalEditor({ conversion, onChange, pageKey }: ConversionGoalEditorProps): JSX.Element {
    const cohortConditionsEnabled = useFeatureFlag('WORKFLOWS_COHORT_CONDITIONS')
    const { eventEntries, cohort } = splitCohortMembershipEntry(conversion?.events)
    const conversionEventFilters = eventEntries[0]?.filters ?? {}
    const conversionWindow = conversion?.window ?? DEFAULT_CONVERSION_WINDOW

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1 items-start">
                <LemonLabel>Detect conversion from property changes</LemonLabel>
                <PropertyFilters
                    buttonText="Add property conversion"
                    buttonClassName="grow-0"
                    propertyFilters={conversion?.filters ?? []}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ]}
                    onChange={(filters) => onChange({ ...conversion, filters })}
                    pageKey={`${pageKey}-properties`}
                    hideBehavioralCohorts
                    operatorAllowlist={WORKFLOW_OPERATOR_ALLOWLIST}
                    logicalRowDivider
                />
            </div>

            <div className="flex flex-col gap-1 items-start w-full">
                <LemonLabel>Detect conversion from events</LemonLabel>
                <HogFlowEventFilters
                    filtersKey={`${pageKey}-events`}
                    filters={conversionEventFilters}
                    setFilters={(newFilters) =>
                        onChange({
                            filters: [],
                            ...conversion,
                            events: joinCohortMembershipEntry(newFilters ? [{ filters: newFilters }] : [], cohort),
                        })
                    }
                    typeKey={`${pageKey}-event`}
                    buttonCopy="Add event"
                />
            </div>

            {cohortConditionsEnabled || cohort ? (
                <div className="flex flex-col gap-1 items-start w-full">
                    <LemonLabel>Detect conversion from cohort membership</LemonLabel>
                    <span className="text-xs text-muted">
                        The person converts when they join or leave this cohort. Only realtime cohorts report these
                        changes.
                    </span>
                    <CohortMembershipEventPicker
                        value={cohort}
                        onChange={(nextCohort) =>
                            onChange({
                                filters: [],
                                ...conversion,
                                events: joinCohortMembershipEntry(eventEntries, nextCohort),
                            })
                        }
                        dataAttr={`${pageKey}-conversion`}
                    />
                </div>
            ) : null}

            <div className="flex flex-col gap-1 items-start">
                <span className="flex gap-1 items-center">
                    <LemonLabel>Conversion window</LemonLabel>
                    <Tooltip title="A person who meets the goal after this window is not counted as converted. The window runs from the moment they enter the workflow.">
                        <IconInfo className="text-secondary" />
                    </Tooltip>
                </span>
                <HogFlowDuration
                    value={conversionWindow}
                    onChange={(next) => {
                        // A cleared amount arrives as a bare unit such as "d", so omitting window
                        // restores the default instead of failing the save.
                        const { window, ...rest } = conversion ?? {}
                        onChange(/\d/.test(next) ? { ...rest, window: next } : rest)
                    }}
                    maxValueForUnit={MAX_CONVERSION_WINDOW_FOR_DURATION_UNIT}
                />
            </div>
        </div>
    )
}
