import { FeatureFlagKey } from 'lib/constants'

export type EventTriggerConfig = {
    type: 'event'
    filters: {
        events?: any[]
        properties?: any[]
        actions?: any[]
        filter_test_accounts?: boolean
    }
}

export type TriggerFrequencyOption = {
    /** trigger_masking hash template (a Hog expression over the trigger event's globals), or null for no masking */
    value: string | null
    label: string
    /** Pin the masking TTL to this many seconds and hide the TTL picker (e.g. calendar-day options) */
    fixedTtl?: number
}

export type TriggerTypeDefinition = {
    value: string
    label: string
    icon: JSX.Element
    description: string
    /** Group label for sectioning in the trigger type dropdown (e.g. 'Surveys', 'Support') */
    group?: string
    featureFlag?: FeatureFlagKey
    /** Return true if this trigger type owns the given event-type config */
    matchConfig?: (config: any) => boolean
    /** Build the initial config when this trigger type is selected */
    buildConfig: () => Record<string, any>
    /** Render the configuration panel (or undefined for no extra config) */
    ConfigComponent?: React.ComponentType<{ node: any }>
    /** Validate the trigger config, returning errors if invalid. Triggers without this use generic validation. */
    validate?: (config: any) => { valid: boolean; errors: Record<string, string> } | null
    /**
     * Show the frequency (trigger_masking) section below the config panel with these options.
     * The generic event trigger's person-keyed options usually don't fit registered triggers —
     * e.g. account events carry no person, so a person-keyed hash would mask globally.
     */
    frequencyOptions?: TriggerFrequencyOption[]
    /** Copy under the "Frequency" heading; defaults to the generic person-centric wording */
    frequencyDescription?: string
}

const triggerTypeDefinitions: TriggerTypeDefinition[] = []

export function registerTriggerType(definition: TriggerTypeDefinition): void {
    if (triggerTypeDefinitions.some((d) => d.value === definition.value)) {
        return
    }
    triggerTypeDefinitions.push(definition)
}

export function getRegisteredTriggerTypes(): TriggerTypeDefinition[] {
    return triggerTypeDefinitions
}
