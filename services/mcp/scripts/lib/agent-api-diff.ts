import * as fs from 'node:fs'
import * as path from 'node:path'

// Claude's tool registry rejects a tool whose input schema is larger than this. Same literal as
// the exec tool check in tests/unit/instructions-formatter-snapshot.test.ts.
export const INPUT_SCHEMA_CHAR_LIMIT = 16_384

const MAX_NAMES_LISTED = 60
const MAX_ROWS = 40
const MAX_CELL_ITEMS = 8
// Well under GitHub's 65,536 char comment limit, which the shared CI report also uses.
const MAX_MARKDOWN_CHARS = 15_000

const DEFINITION_FILES = ['tool-definitions.json', 'generated-tool-definitions.json']
const SCHEMA_SNAPSHOT_DIR = 'services/mcp/tests/unit/__snapshots__/tool-schemas'
const SCHEMA_DIR = 'services/mcp/schema'

export interface ToolDefinition {
    title?: string
    category?: string
    description?: string
    required_scopes?: string[]
    annotations?: Record<string, unknown>
}

export interface ToolSurface {
    definitions: Record<string, ToolDefinition>
    // Input JSON schema per tool, as written by the tool-schema snapshot test.
    schemas: Record<string, { properties?: Record<string, unknown> }>
}

export interface ToolChange {
    name: string
    paramsAdded: string[]
    paramsRemoved: string[]
    scopesAdded: string[]
    scopesRemoved: string[]
    annotationChanges: string[]
    titleChanged: boolean
    descriptionChanged: boolean
    categoryChanged: boolean
    // The schema differs although no listed field above shows it, for example a property type.
    schemaChanged: boolean
    sizeBefore: number | null
    sizeAfter: number | null
}

export interface AgentApiDiff {
    added: { name: string; size: number | null }[]
    removed: string[]
    changed: ToolChange[]
    overLimit: { name: string; size: number; wasSize: number | null }[]
}

function readJson(file: string): unknown {
    return JSON.parse(fs.readFileSync(file, 'utf-8'))
}

/**
 * Read the tool surface under a repo root. Returns null when either source is missing, so a
 * checkout that predates the snapshots degrades to "no diff" instead of failing the run.
 */
export function loadToolSurface(root: string): ToolSurface | null {
    const schemaDir = path.join(root, SCHEMA_SNAPSHOT_DIR)
    const definitionPaths = DEFINITION_FILES.map((file) => path.join(root, SCHEMA_DIR, file))
    if (!fs.existsSync(schemaDir) || !definitionPaths.every((file) => fs.existsSync(file))) {
        return null
    }

    // Generated definitions win over hand-written ones, the same precedence the server uses.
    const definitions: Record<string, ToolDefinition> = {}
    for (const file of definitionPaths) {
        Object.assign(definitions, readJson(file))
    }

    const schemas: ToolSurface['schemas'] = {}
    for (const entry of fs.readdirSync(schemaDir, { withFileTypes: true })) {
        if (entry.isFile() && entry.name.endsWith('.json')) {
            schemas[entry.name.replace(/\.json$/, '')] = readJson(
                path.join(schemaDir, entry.name)
            ) as ToolSurface['schemas'][string]
        }
    }
    return { definitions, schemas }
}

// Names, params and scopes come from PR-controlled YAML and go into a shared bot comment, so
// anything that could close a code span or forge a report marker is replaced.
function safe(value: string): string {
    return value.replace(/[^A-Za-z0-9_:.\-/ ]/g, '?')
}

function sorted(values: Iterable<string>): string[] {
    return [...values].sort()
}

function subtract(from: Iterable<string>, remove: Set<string>): string[] {
    return sorted([...from].filter((value) => !remove.has(value)))
}

function paramNames(surface: ToolSurface, name: string): Set<string> {
    return new Set(Object.keys(surface.schemas[name]?.properties ?? {}))
}

// The server drops these root keys before advertising a schema (see toMcpInputSchema), so the
// size counts without them to stay close to what Claude's registry measures.
function advertisedSchema(surface: ToolSurface, name: string): object | null {
    const schema = surface.schemas[name]
    if (!schema) {
        return null
    }
    const { $schema: _schema, additionalProperties: _additional, ...rest } = schema as Record<string, unknown>
    return rest
}

function schemaSize(surface: ToolSurface, name: string): number | null {
    const schema = advertisedSchema(surface, name)
    return schema ? JSON.stringify(schema).length : null
}

function schemaText(surface: ToolSurface, name: string): string | null {
    const schema = advertisedSchema(surface, name)
    return schema ? JSON.stringify(schema) : null
}

function diffAnnotations(before: Record<string, unknown> = {}, after: Record<string, unknown> = {}): string[] {
    return sorted(new Set([...Object.keys(before), ...Object.keys(after)]))
        .filter((key) => before[key] !== after[key])
        .map((key) => `${safe(key)}: ${safe(String(before[key] ?? 'unset'))} -> ${safe(String(after[key] ?? 'unset'))}`)
}

function toolNames(surface: ToolSurface): Set<string> {
    return new Set([...Object.keys(surface.definitions), ...Object.keys(surface.schemas)])
}

export function diffToolSurfaces(base: ToolSurface, head: ToolSurface): AgentApiDiff {
    const baseNames = toolNames(base)
    const headNames = toolNames(head)

    const diff: AgentApiDiff = {
        added: subtract(headNames, baseNames).map((name) => ({ name, size: schemaSize(head, name) })),
        removed: subtract(baseNames, headNames),
        changed: [],
        overLimit: [],
    }

    for (const name of sorted(headNames)) {
        const sizeAfter = schemaSize(head, name)
        const sizeBefore = baseNames.has(name) ? schemaSize(base, name) : null
        const wasOverLimit = sizeBefore !== null && sizeBefore >= INPUT_SCHEMA_CHAR_LIMIT
        if (sizeAfter !== null && sizeAfter >= INPUT_SCHEMA_CHAR_LIMIT && !wasOverLimit) {
            diff.overLimit.push({ name, size: sizeAfter, wasSize: sizeBefore })
        }
        if (!baseNames.has(name)) {
            continue
        }

        const baseParams = paramNames(base, name)
        const headParams = paramNames(head, name)
        const baseScopes = new Set(base.definitions[name]?.required_scopes ?? [])
        const headScopes = new Set(head.definitions[name]?.required_scopes ?? [])
        const change: ToolChange = {
            name,
            paramsAdded: subtract(headParams, baseParams),
            paramsRemoved: subtract(baseParams, headParams),
            scopesAdded: subtract(headScopes, baseScopes),
            scopesRemoved: subtract(baseScopes, headScopes),
            annotationChanges: diffAnnotations(
                base.definitions[name]?.annotations,
                head.definitions[name]?.annotations
            ),
            titleChanged: base.definitions[name]?.title !== head.definitions[name]?.title,
            categoryChanged: base.definitions[name]?.category !== head.definitions[name]?.category,
            descriptionChanged: base.definitions[name]?.description !== head.definitions[name]?.description,
            // Snapshot files are key-sorted, so equal schemas serialize to equal text.
            schemaChanged: schemaText(base, name) !== schemaText(head, name),
            sizeBefore,
            sizeAfter,
        }
        const hasChange =
            change.paramsAdded.length > 0 ||
            change.paramsRemoved.length > 0 ||
            change.scopesAdded.length > 0 ||
            change.scopesRemoved.length > 0 ||
            change.annotationChanges.length > 0 ||
            change.titleChanged ||
            change.descriptionChanged ||
            change.categoryChanged ||
            change.schemaChanged
        if (hasChange) {
            diff.changed.push(change)
        }
    }
    return diff
}

function chars(size: number | null): string {
    return size === null ? 'n/a' : size.toLocaleString('en-US')
}

function listNames(items: { name: string; note?: string }[]): string {
    const shown = items.slice(0, MAX_NAMES_LISTED)
    const more = items.length > shown.length ? `, and ${items.length - shown.length} more` : ''
    return shown.map(({ name, note }) => `\`${safe(name)}\`${note ? ` (${note})` : ''}`).join(', ') + more
}

function capItems(items: string[]): string {
    const shown = items.slice(0, MAX_CELL_ITEMS)
    return items.length > shown.length ? `${shown.join(' ')} ... ${items.length - shown.length} more` : shown.join(' ')
}

function paramsCell(change: ToolChange): string {
    const parts = [
        ...change.paramsAdded.map((param) => `+\`${safe(param)}\``),
        ...change.paramsRemoved.map((param) => `-\`${safe(param)}\``),
    ]
    const looksRenamed = change.paramsAdded.length > 0 && change.paramsRemoved.length > 0
    return capItems(parts) + (looksRenamed ? ' (rename?)' : '')
}

function scopesCell(change: ToolChange): string {
    return capItems([
        ...change.scopesAdded.map((scope) => `+\`${safe(scope)}\``),
        ...change.scopesRemoved.map((scope) => `-\`${safe(scope)}\``),
    ])
}

function sizeCell(change: ToolChange): string {
    if (change.sizeBefore !== change.sizeAfter) {
        return `${chars(change.sizeBefore)} -> ${chars(change.sizeAfter)}`
    }
    return change.schemaChanged ? 'schema changed' : ''
}

/** Compact markdown for a PR comment. Empty string when nothing changed for agents. */
export function renderAgentApiDiff(diff: AgentApiDiff): string {
    if (diff.added.length + diff.removed.length + diff.changed.length === 0) {
        return ''
    }

    const lines: string[] = []
    if (diff.added.length > 0) {
        const items = diff.added.map(({ name, size }) => ({
            name,
            note: size === null ? undefined : `${chars(size)} chars`,
        }))
        lines.push(`**Tools added (${diff.added.length}):** ${listNames(items)}`)
    }
    if (diff.removed.length > 0) {
        lines.push(`**Tools removed (${diff.removed.length}):** ${listNames(diff.removed.map((name) => ({ name })))}`)
    }
    if (diff.overLimit.length > 0) {
        const items = diff.overLimit.map(({ name, size, wasSize }) => ({
            name,
            note: `${chars(size)}, was ${chars(wasSize)}`,
        }))
        lines.push(
            `**Input schema now at or over ${INPUT_SCHEMA_CHAR_LIMIT.toLocaleString('en-US')} chars (${diff.overLimit.length}):** ${listNames(items)}`
        )
    }

    if (diff.changed.length > 0) {
        const rows = diff.changed.slice(0, MAX_ROWS).map((change) => {
            const annotations = change.annotationChanges.join('; ')
            const title = [
                change.titleChanged ? 'title changed' : '',
                change.descriptionChanged ? 'description changed' : '',
                change.categoryChanged ? 'category changed' : '',
            ]
                .filter(Boolean)
                .join('; ')
            return `| \`${safe(change.name)}\` | ${paramsCell(change)} | ${scopesCell(change)} | ${[annotations, title].filter(Boolean).join('; ')} | ${sizeCell(change)} |`
        })
        lines.push(
            '',
            `**Tools changed (${diff.changed.length}):**`,
            '',
            '| Tool | Params | Scopes | Annotations | Schema chars |',
            '| --- | --- | --- | --- | --- |',
            ...rows
        )
        if (diff.changed.length > rows.length) {
            lines.push('', `...and ${diff.changed.length - rows.length} more changed tools.`)
        }
    }
    const markdown = lines.join('\n') + '\n'
    if (markdown.length <= MAX_MARKDOWN_CHARS) {
        return markdown
    }
    const cut = markdown.slice(0, markdown.lastIndexOf('\n', MAX_MARKDOWN_CHARS))
    return `${cut}\n\n...truncated, ${diff.changed.length} changed tools in total.\n`
}
