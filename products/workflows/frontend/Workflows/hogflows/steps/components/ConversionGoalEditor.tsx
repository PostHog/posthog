import { IconInfo } from '@posthog/icons'
import { LemonLabel, Tooltip } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { HogFlowEventFilters, WORKFLOW_OPERATOR_ALLOWLIST } from '../../filters/HogFlowFilters'
import { HogFlowDuration, MAX_CONVERSION_WINDOW_FOR_DURATION_UNIT } from './HogFlowDuration'

// Structural shape of a workflow conversion goal, compatible with both the frontend HogFlow
// type and the generated HogFlowConversionApi type.
export interface ConversionGoalValue {
    window?: string | null
    window_minutes?: number | null
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
// The worker measures a legacy window_minutes at most this long, so a longer stored value is shown
// as what it actually measures rather than as a number the API would now reject.
const LEGACY_CONVERSION_WINDOW_CEILING_MINUTES = 90 * 24 * 60

function conversionWindowFromMinutes(minutes: number): string {
    const capped = Math.min(minutes, LEGACY_CONVERSION_WINDOW_CEILING_MINUTES)
    if (capped % (24 * 60) === 0) {
        return `${capped / (24 * 60)}d`
    }
    if (capped % 60 === 0) {
        return `${capped / 60}h`
    }
    return `${capped}m`
}

export function ConversionGoalEditor({ conversion, onChange, pageKey }: ConversionGoalEditorProps): JSX.Element {
    const conversionEventFilters = conversion?.events?.[0]?.filters ?? {}
    const legacyWindowMinutes = conversion?.window_minutes
    const conversionWindow =
        conversion?.window ??
        (legacyWindowMinutes ? conversionWindowFromMinutes(legacyWindowMinutes) : DEFAULT_CONVERSION_WINDOW)

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
                            events: newFilters ? [{ filters: newFilters }] : undefined,
                        })
                    }
                    typeKey={`${pageKey}-event`}
                    buttonCopy="Add event"
                />
            </div>

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
                        // Dropping window_minutes keeps the two forms from arriving together, which
                        // the API rejects. A cleared amount arrives as a bare unit such as "d", so
                        // omitting window restores the default instead of failing the save.
                        const { window_minutes, window, ...rest } = conversion ?? {}
                        onChange(/\d/.test(next) ? { ...rest, window: next } : rest)
                    }}
                    maxValueForUnit={MAX_CONVERSION_WINDOW_FOR_DURATION_UNIT}
                />
            </div>
        </div>
    )
}
