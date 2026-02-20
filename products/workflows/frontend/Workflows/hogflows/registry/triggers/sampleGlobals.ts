import { CyclotronJobInputSchemaType } from '../../steps/types'
import type { HogFlow } from '../../types'
import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

// Shared sample data for hog function autocomplete

export const SAMPLE_PERSON = {
    id: 'person123',
    properties: {
        email: 'user@example.com',
        name: 'John Doe',
    },
}

export const SAMPLE_GROUPS = {}

export const SAMPLE_EVENT = {
    event: 'example_event',
    distinct_id: 'user123',
    properties: {
        $current_url: 'https://example.com',
    },
    timestamp: '2024-01-01T12:00:00Z',
}

export const SAMPLE_WEBHOOK_REQUEST = {
    method: 'POST',
    headers: {},
    body: {},
    params: {},
}

const VARIABLE_TYPE_SAMPLES: Record<string, any> = {
    string: 'example_value',
    number: 123,
    boolean: true,
    dictionary: {},
    json: {},
}

export function buildVariablesSample(variables: CyclotronJobInputSchemaType[] | null | undefined): Record<string, any> {
    const result: Record<string, any> = {}
    if (!variables) {
        return result
    }
    for (const variable of variables) {
        result[variable.key] = VARIABLE_TYPE_SAMPLES[variable.type] ?? null
    }
    return result
}

const DEFAULT_TRIGGER_GLOBALS: Record<string, () => Record<string, any>> = {
    event: () => ({
        event: SAMPLE_EVENT,
        person: SAMPLE_PERSON,
        groups: SAMPLE_GROUPS,
    }),
    webhook: () => ({
        request: SAMPLE_WEBHOOK_REQUEST,
    }),
}

function getDefaultTriggerGlobals(triggerType: string | undefined): Record<string, any> {
    return DEFAULT_TRIGGER_GLOBALS[triggerType ?? '']?.() ?? {}
}

export function buildTriggerSampleGlobals(workflow: HogFlow | null | undefined): Record<string, any> {
    const triggerConfig = workflow?.actions?.find((a) => a.type === 'trigger')?.config
    const matchingType = triggerConfig ? getRegisteredTriggerTypes().find((t) => t.matchConfig?.(triggerConfig)) : null
    const customGlobals = matchingType?.buildSampleGlobals?.(workflow)

    return customGlobals ?? getDefaultTriggerGlobals(workflow?.trigger?.type)
}

export function buildSampleGlobals(workflow: HogFlow | null | undefined): Record<string, any> {
    return {
        variables: buildVariablesSample(workflow?.variables),
        ...buildTriggerSampleGlobals(workflow),
    }
}
