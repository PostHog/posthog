import { MCPToolResultError, PostHogApiError, PostHogValidationError } from '@/lib/errors'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Entities a stack in the project manages are changed through their definitions in a repository
 * (a `.ph` folder that `hog check` evaluates). Two answers keep an agent from working
 * around that: a create tool for a kind the project keeps in code answers with the steps instead of
 * creating, and a write the API refuses with `managed_in_code` answers with the file to edit.
 */

// One row of `GET /api/projects/{id}/stacks/managed_kinds/`.
export interface ManagedKind {
    kind: string
    stack_name: string
    repository: string | null
    definitions: number
    redirect_creates: boolean
}

/** The rows of a managed-kinds answer that have the expected shape. Anything else is left out. */
export function parseManagedKinds(results: unknown): ManagedKind[] {
    if (!Array.isArray(results)) {
        return []
    }
    return results.flatMap((row): ManagedKind[] => {
        if (typeof row !== 'object' || row === null) {
            return []
        }
        const { kind, stack_name, repository, definitions, redirect_creates } = row as Record<string, unknown>
        if (typeof kind !== 'string' || typeof stack_name !== 'string' || typeof redirect_creates !== 'boolean') {
            return []
        }
        return [
            {
                kind,
                stack_name,
                repository: typeof repository === 'string' && repository ? repository : null,
                definitions: typeof definitions === 'number' ? definitions : 0,
                redirect_creates,
            },
        ]
    })
}

// What a program reads from a refused create or write. The CLI library and the SDK pass it on.
export interface ManagedInCode {
    reason: 'create_redirected' | 'write_refused'
    kind?: string
    stacks: { name: string; repository: string | null }[]
    source?: { file: string; export?: string }
    fields?: string[]
}

/**
 * The tools that create an entity of a natural-key kind, by kind. The first tool of each kind is the
 * one `@posthog/sdk/stack`'s registry validates that kind's body with, and a test holds the two
 * together. Not here, on purpose:
 * - `context-wiki-page-update` and `task-context-wiki-page-update` write a page whether or not it
 *   exists, so they are writes, and the API refuses one to a managed page with `managed_in_code`.
 * - `experiment-create` can create a flag as a side effect. An experiment is not a natural-key kind,
 *   and a flag key a stack defines already exists, so the experiment uses it instead of creating one.
 * - `feature-flags-copy-flags-create` creates flags in other projects, whose stacks this project's
 *   lookup does not cover.
 */
export const CREATE_TOOLS_BY_KIND: Readonly<Record<string, readonly string[]>> = {
    event: ['event-definition-create'],
    property_group: ['schema-property-group-create'],
    flag: ['create-feature-flag'],
    model: ['view-create'],
    endpoint: ['endpoint-create'],
    metric: ['data-catalog-metric-create'],
    context_page: [],
}

const KIND_BY_CREATE_TOOL: ReadonlyMap<string, string> = new Map(
    Object.entries(CREATE_TOOLS_BY_KIND).flatMap(([kind, tools]) => tools.map((tool) => [tool, kind] as const))
)

export function kindCreatedBy(toolName: string): string | undefined {
    return KIND_BY_CREATE_TOOL.get(toolName)
}

const PLURALS: Readonly<Record<string, string>> = {
    event: 'Event definitions',
    property_group: 'Property groups',
    flag: 'Feature flags',
    model: 'Models',
    endpoint: 'Endpoints',
    metric: 'Metrics',
    context_page: 'Context pages',
}

const SINGULARS: Readonly<Record<string, string>> = {
    event: 'event definition',
    property_group: 'property group',
    flag: 'feature flag',
    model: 'model',
    endpoint: 'endpoint',
    metric: 'metric',
    context_page: 'context page',
}

function stackText(stack: { name: string; repository: string | null }): string {
    return stack.repository
        ? `the stack ${stack.name} in the repository ${stack.repository}`
        : `the stack ${stack.name}`
}

function listText(items: string[]): string {
    return items.length <= 1 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** The answer to a create tool for a kind the project keeps in code. */
export function createRedirectMessage(kind: string, rows: readonly ManagedKind[]): string {
    const stacks = rows.map((row) => ({ name: row.stack_name, repository: row.repository }))
    const plural = PLURALS[kind] ?? `Entities of the kind ${kind}`
    const singular = SINGULARS[kind] ?? kind
    const where =
        stacks.length === 1
            ? 'to the folder of that stack in its repository'
            : 'to the folder of the stack that should own it, in the repository of that stack'
    return [
        `Nothing was created. ${plural} in this project are managed in code by ${listText(stacks.map(stackText))}, so a new ${singular} is added there as a definition, not through this tool.`,
        '',
        `To add the ${singular}:`,
        `1. Add a definition for it ${where}.`,
        '2. Run `hog check` in that repository and fix any problems it reports.',
        '3. Open a pull request with the change.',
        '',
        `Do not create this ${singular} with another tool or the API.`,
    ].join('\n')
}

/** The answer to a write the API refused because a stack manages the entity. */
export function writeRefusedMessage(managed: ManagedInCode): string {
    const stack = managed.stacks[0]
    const owner = stack ? `managed in code by ${stackText(stack)}` : 'managed in code'
    const lines = [`Nothing was changed. The entity this call changes is ${owner}.`]
    if (managed.source?.file) {
        const exported = managed.source.export ? `the export ${managed.source.export} in ` : ''
        lines.push(
            `Its definition is ${exported}${managed.source.file}. Edit that file instead, run \`hog check\`, and open a pull request.`
        )
    } else {
        lines.push('Edit its definition in that repository instead, run `hog check`, and open a pull request.')
    }
    if (managed.fields && managed.fields.length > 0) {
        lines.push(
            '',
            `Code owns these fields: ${managed.fields.join(', ')}. Fields code does not own can still be changed with this tool.`
        )
    }
    return lines.join('\n')
}

/**
 * Raised instead of running a redirected create, and instead of the API's 409 for a managed entity.
 * Typed as a validation result, so the hosted server answers with an error the agent reads and
 * corrects from, and reports no exception.
 */
export class ManagedInCodeError extends MCPToolResultError {
    constructor(
        message: string,
        readonly managed: ManagedInCode
    ) {
        super(
            message,
            'validation',
            managed.reason === 'create_redirected' ? 'create_managed_in_code' : 'managed_in_code'
        )
        this.name = 'ManagedInCodeError'
    }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseJson(text: string): unknown {
    try {
        return JSON.parse(text)
    } catch {
        return undefined
    }
}

// The API puts the stack, repository, source and fields under `extra`, beside `code` and `detail`.
function managedFromBody(code: unknown, extra: unknown): ManagedInCode | undefined {
    if (code !== 'managed_in_code') {
        return undefined
    }
    const details = isRecord(extra) ? extra : {}
    const source = isRecord(details.source) ? details.source : undefined
    const file = typeof source?.file === 'string' && source.file ? source.file : undefined
    const exported = typeof source?.export === 'string' && source.export ? source.export : undefined
    const fields = Array.isArray(details.fields) ? details.fields.filter((field) => typeof field === 'string') : []
    return {
        reason: 'write_refused',
        ...(typeof details.kind === 'string' ? { kind: details.kind } : {}),
        stacks:
            typeof details.stack === 'string'
                ? [
                      {
                          name: details.stack,
                          repository: typeof details.repository === 'string' ? details.repository : null,
                      },
                  ]
                : [],
        ...(file ? { source: { file, ...(exported ? { export: exported } : {}) } } : {}),
        ...(fields.length > 0 ? { fields } : {}),
    }
}

/** The managed-in-code refusal anywhere in an error's cause chain, or undefined. */
export function findManagedInCode(error: unknown): ManagedInCode | undefined {
    const seen = new Set<unknown>()
    for (
        let current = error;
        current instanceof Error && !seen.has(current);
        current = (current as { cause?: unknown }).cause
    ) {
        seen.add(current)
        if (current instanceof ManagedInCodeError) {
            return current.managed
        }
        if (current instanceof PostHogApiError && current.status === 409) {
            const body = parseJson(current.body)
            const managed = isRecord(body) ? managedFromBody(body.code, body.extra) : undefined
            if (managed) {
                return managed
            }
        }
        if (current instanceof PostHogValidationError) {
            const managed = managedFromBody(current.code, current.extra)
            if (managed) {
                return managed
            }
        }
    }
    return undefined
}

async function redirectRows(context: Context, kind: string): Promise<ManagedKind[]> {
    try {
        const projectId = await context.stateManager.getProjectId()
        const rows = projectId ? await context.stateManager.getOrFetchManagedKinds(projectId) : undefined
        return (rows ?? []).filter((row) => row.kind === kind && row.redirect_creates)
    } catch {
        // A lookup that can't run leaves the tool as it was.
        return []
    }
}

const WRAPPED = Symbol('managed-in-code')

/** Wraps a tool so a create for a kind kept in code is redirected, and a refused write names its file. */
export function withManagedInCode<T extends ToolBase<ZodObjectAny>>(tool: T): T {
    if ((tool as { [WRAPPED]?: true })[WRAPPED]) {
        return tool
    }
    const kind = kindCreatedBy(tool.name)
    const handler = tool.handler
    return {
        ...tool,
        [WRAPPED]: true,
        handler: async (context: Context, params: unknown) => {
            if (kind) {
                const rows = await redirectRows(context, kind)
                if (rows.length > 0) {
                    throw new ManagedInCodeError(createRedirectMessage(kind, rows), {
                        reason: 'create_redirected',
                        kind,
                        stacks: rows.map((row) => ({ name: row.stack_name, repository: row.repository })),
                    })
                }
            }
            try {
                return await handler(context, params as never)
            } catch (error) {
                const managed = error instanceof ManagedInCodeError ? undefined : findManagedInCode(error)
                if (managed) {
                    throw new ManagedInCodeError(writeRefusedMessage(managed), managed)
                }
                throw error
            }
        },
    }
}
