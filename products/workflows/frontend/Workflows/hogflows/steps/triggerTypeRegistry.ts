export type TriggerTypeDefinition = {
    value: string
    label: string
    icon: JSX.Element
    description: string
    featureFlag?: string
    /** Return true if this trigger type owns the given event-type config */
    matchConfig?: (config: any) => boolean
    /** Build the initial config when this trigger type is selected */
    buildConfig: () => Record<string, any>
    /** Render the configuration panel (or undefined for no extra config) */
    ConfigComponent?: React.ComponentType<{ node: any }>
}

const triggerTypeDefinitions: TriggerTypeDefinition[] = []

export function registerTriggerType(definition: TriggerTypeDefinition): void {
    triggerTypeDefinitions.push(definition)
}

export function getRegisteredTriggerTypes(): TriggerTypeDefinition[] {
    return triggerTypeDefinitions
}
