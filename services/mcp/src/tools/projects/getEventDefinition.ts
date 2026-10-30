import type { z } from 'zod'

import { PostHogApiError, wrapError } from '@/lib/errors'
import { EventDefinitionGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EventDefinitionGetSchema

type Params = z.infer<typeof schema>

interface EventDefinitionOwner {
    id: number
    email: string
    first_name?: string
    last_name?: string
}

/** A miss is data, not an error: agents look an event up to check whether it exists before creating it. */
type Result =
    | {
          found: true
          id: string
          name: string
          description: string | null
          owner: EventDefinitionOwner | null
          tags: unknown[]
          verified: boolean
          hidden: boolean | null
          first_seen_at: string | null
          last_seen_at: string | null
          url: string
      }
    | { found: false; eventName: string; message: string }

export const getEventDefinitionHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.projects().getEventDefinition({ projectId, eventName: params.eventName })

    if (!result.success) {
        if (result.error instanceof PostHogApiError && result.error.status === 404) {
            return {
                found: false,
                eventName: params.eventName,
                message:
                    `No event definition named "${params.eventName}" exists in this project. ` +
                    'Call `read-data-schema` with { "query": { "kind": "events" } } to list events, ' +
                    'or `event-definition-create` to define it.',
            }
        }
        throw wrapError(`Failed to get event definition: ${result.error.message}`, result.error)
    }

    const definition = result.data
    const owner = definition.owner

    return {
        found: true,
        id: definition.id,
        name: definition.name,
        description: definition.description ?? null,
        owner: owner
            ? { id: owner.id, email: owner.email, first_name: owner.first_name, last_name: owner.last_name }
            : null,
        tags: definition.tags ?? [],
        verified: definition.verified ?? false,
        hidden: definition.hidden ?? null,
        // The UI calls this "First seen". It is null for a definition created before any event arrived.
        first_seen_at: definition.created_at,
        last_seen_at: definition.last_seen_at,
        url: `${context.api.getProjectBaseUrl(projectId)}/data-management/events/${encodeURIComponent(definition.id)}`,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'event-definition-get',
    schema,
    handler: getEventDefinitionHandler,
})

export default tool
