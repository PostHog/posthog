import posthog from 'posthog-js'

export enum MAX_AI_ENDPOINT_OPERATION {
    CREATE = 'create',
    UPDATE = 'update',
}

/**
 * Captures exceptions that occur during MaxAI endpoint operations
 * for analytics and debugging purposes.
 */
export function captureMaxAIEndpointException(
    error: string | undefined,
    operation: MAX_AI_ENDPOINT_OPERATION,
    endpointName?: string
): void {
    const operationVerb = operation === MAX_AI_ENDPOINT_OPERATION.CREATE ? 'creating' : 'updating'
    posthog.captureException(error || `Undefined error when ${operationVerb} endpoint with PostHog AI`, {
        action: `max-ai-endpoint-${operation}-failed`,
        endpoint_name: endpointName,
        operation,
    })
}
