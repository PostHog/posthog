/**
 * Shared display helpers for the PostHog single-exec MCP tool. The `posthog` MCP server exposes one
 * outer `exec` tool whose `command` string carries the real intent (`tools` / `search` / `info` /
 * `schema` / `call <sub-tool>`). Both the thread tool-card renderer and the permission card need the
 * same human-friendly label + input preview. Tokenization stays in the headless `utils/posthogExec`
 * utility so non-display consumers do not import this component module.
 */

import { parseExecCall, parseExecCommand, splitFirstToken } from '../../utils/posthogExec'

export interface PostHogExecDisplay {
    label: string
    input?: string
}

function readExplicitInput(value: unknown): string | undefined {
    if (value === undefined || value === null) {
        return undefined
    }
    if (typeof value === 'string') {
        return value.trim() || undefined
    }
    try {
        return JSON.stringify(value)
    } catch {
        return undefined
    }
}

/**
 * Unwraps an `exec` invocation's `command` (and optional explicit `input`) into a friendly label and
 * input preview. Returns null when the payload isn't a recognizable `exec` command, so callers can
 * fall back to generic rendering.
 */
export function getPostHogExecDisplay(toolInput: unknown): PostHogExecDisplay | null {
    if (!toolInput || typeof toolInput !== 'object') {
        return null
    }
    const obj = toolInput as { command?: unknown; input?: unknown }
    if (typeof obj.command !== 'string') {
        return null
    }

    const { verb, rest } = parseExecCommand(obj.command)
    if (!verb) {
        return null
    }
    const explicitInput = readExplicitInput(obj.input)

    switch (verb) {
        case 'tools':
            return { label: 'List tools', input: undefined }
        case 'search':
            return {
                label: 'Search tools',
                input: explicitInput ?? (rest.length > 0 ? rest : undefined),
            }
        case 'info':
            return rest.length > 0
                ? { label: `Read ${rest}`, input: undefined }
                : { label: 'Read tool', input: undefined }
        case 'schema': {
            const { head: subTool, rest: fieldPath } = splitFirstToken(rest)
            if (!subTool) {
                return { label: 'Inspect schema', input: undefined }
            }
            const path = explicitInput ?? (fieldPath.length > 0 ? fieldPath : undefined)
            return {
                label: path ? `Inspect ${subTool}.${path}` : `Inspect ${subTool} fields`,
                input: undefined,
            }
        }
        case 'call': {
            const { subTool, args } = parseExecCall(rest)
            if (!subTool) {
                return null
            }
            return {
                label: subTool,
                input: explicitInput ?? (args.length > 0 ? args : undefined),
            }
        }
    }
}

export function formatPostHogExecBody(input: string | undefined): string | undefined {
    if (!input) {
        return undefined
    }
    try {
        const parsed = JSON.parse(input)
        if (parsed && typeof parsed === 'object') {
            return JSON.stringify(parsed, null, 2)
        }
    } catch {
        // Non-JSON args, such as a search regex, are already displayable.
    }
    return input
}
