/**
 * Native tool registry. Two methods land everything the runner and authoring
 * layer need:
 *   - get(id)   — runner lookup; throws if unknown.
 *   - list()    — authoring catalog (description, args schema, requires).
 *
 * Tools are statically registered at module load. To add a tool: create the
 * file, import its default export here, push into ALL_TOOLS. Tests live next
 * to the tool. No magic discovery.
 */

import { NativeTool, NativeToolSchema } from '@posthog/agent-shared'

import { loadSkill } from './tools/load-skill'
import { askForInputTool, endSessionTool, emitEventTool } from './tools/meta'
import { posthogPersonsSearchV1 } from './tools/posthog-persons-search.v1'
import { posthogQueryV1 } from './tools/posthog-query.v1'
import { slackPostMessageV1, slackUpdateMessageV1, slackReactV1 } from './tools/slack.v1'
import { webFetchV1 } from './tools/web-fetch.v1'
import { webSearchV1 } from './tools/web-search.v1'

export const ALL_TOOLS: NativeTool[] = [
    posthogQueryV1,
    posthogPersonsSearchV1,
    slackPostMessageV1,
    slackUpdateMessageV1,
    slackReactV1,
    webFetchV1,
    webSearchV1,
    askForInputTool,
    endSessionTool,
    emitEventTool,
    loadSkill,
]

const BY_ID = new Map<string, NativeTool>(ALL_TOOLS.map((t) => [t.id, t]))

export function getNativeTool(id: string): NativeTool {
    const t = BY_ID.get(id)
    if (!t) {
        throw new Error(`unknown native tool: ${id}`)
    }
    return t
}

export function hasNativeTool(id: string): boolean {
    return BY_ID.has(id)
}

export interface NativeToolCatalogEntry {
    id: string
    schema: NativeToolSchema
}

/** Catalog view for the authoring MCP. Strips the run() function. */
export function listNativeTools(): NativeToolCatalogEntry[] {
    return ALL_TOOLS.map((t) => ({ id: t.id, schema: t.schema }))
}
