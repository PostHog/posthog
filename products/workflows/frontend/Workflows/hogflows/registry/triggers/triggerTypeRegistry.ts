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

export type TriggerTypeDefinition = {
    value: string
    label: string
    icon: JSX.Element
    description: string
    featureFlag?: FeatureFlagKey
    /** Return true if this trigger type owns the given event-type config */
    matchConfig?: (config: any) => boolean
    /** Build the initial config when this trigger type is selected */
    buildConfig: () => Record<string, any>
    /** Render the configuration panel (or undefined for no extra config) */
    ConfigComponent?: React.ComponentType<{ node: any }>
    /** Validate the trigger config, returning errors if invalid. Triggers without this use generic validation. */
    validate?: (config: any) => { valid: boolean; errors: Record<string, string> } | null
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
