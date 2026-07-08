import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

import appUrlManifest from './app-url-manifest.json'
import type { AppUrlManifest } from './types'

// Canonical route table generated from the frontend's `urls` registry (see
// frontend/src/scenes/appUrlManifest.ts). The model must never hand-build entity links — slugs and
// project/host prefixes are easy to get wrong (a person UUID lives at `/persons/<uuid>`, a distinct
// id at `/person/<id>`) — so this tool resolves them from the same definitions the app ships.
const MANIFEST = appUrlManifest as AppUrlManifest

// template -> scope. Templates can repeat across builders, but scope is a function of the path, so
// any entry for a given template carries the same scope.
const SCOPE_BY_TEMPLATE = new Map<string, 'project' | 'global'>()
for (const entry of Object.values(MANIFEST)) {
    SCOPE_BY_TEMPLATE.set(entry.template, entry.scope)
}

// Full catalog of canonical path templates, embedded in the `url` description so an agent inspecting
// the tool (exec `info`) sees every linkable path up front — the `{placeholders}` are the params to
// fill. Generated from the manifest (itself generated from the frontend's `urls`) so it never drifts.
const URL_CATALOG = [...SCOPE_BY_TEMPLATE.keys()].sort().join('\n')

const PLACEHOLDER = /\{([^}]+)\}/g

function placeholdersOf(template: string): string[] {
    return [...template.matchAll(PLACEHOLDER)].map((match) => match[1]!)
}

const schema = z.object({
    url: z
        .string()
        .describe(
            'A path template copied verbatim from the catalog below (e.g. `/persons/{uuid}`). Its ' +
                "`{placeholders}` are filled from `params`. These slugs come from PostHog's canonical route " +
                'table, so they are always correct — never pass a path that is not in this list.\n\n' +
                URL_CATALOG
        ),
    params: z
        .record(z.string(), z.string())
        .default({})
        .describe(
            'Values for the `{placeholders}` in the chosen path, e.g. {"uuid": "..."} for `/persons/{uuid}` ' +
                'or {"id": "...", "timestamp": "..."} for `/events/{id}/{timestamp}`. Must match the placeholders ' +
                'exactly; pass {} for a path with none.'
        ),
})

type Params = z.infer<typeof schema>

interface AppUrlResult {
    /** Full, canonical, clickable PostHog URL. Surface this verbatim — do not rewrite it. */
    url: string
}

function substitute(template: string, params: Record<string, string>): string {
    return template.replace(PLACEHOLDER, (_match, name: string) => encodeURIComponent(params[name] ?? ''))
}

export const generateAppUrlHandler: ToolBase<typeof schema, AppUrlResult>['handler'] = async (
    context: Context,
    params: Params
): Promise<AppUrlResult> => {
    const scope = SCOPE_BY_TEMPLATE.get(params.url)
    if (!scope) {
        throw new Error(
            `Unknown url "${params.url}". Pick a path template from this tool's catalog (run \`info generate-app-url\`).`
        )
    }

    const required = placeholdersOf(params.url)
    const provided = Object.keys(params.params)
    const missing = required.filter((name) => !(name in params.params))
    const unexpected = provided.filter((name) => !required.includes(name))
    if (missing.length > 0 || unexpected.length > 0) {
        const issues: string[] = []
        if (missing.length > 0) {
            issues.push(`missing: ${missing.join(', ')}`)
        }
        if (unexpected.length > 0) {
            issues.push(`unexpected: ${unexpected.join(', ')}`)
        }
        const expected = required.length > 0 ? `[${required.join(', ')}]` : '(none)'
        throw new Error(`params for "${params.url}" must be exactly ${expected} — ${issues.join('; ')}.`)
    }

    // `project` paths get `${publicBaseUrl}/project/:id`; `global` (org/account/auth) paths get the
    // bare public host. `@current` resolves to the bare host without a project segment.
    let baseUrl: string
    if (scope === 'project') {
        const projectId = await context.stateManager.getProjectId()
        baseUrl = context.api.getProjectBaseUrl(projectId)
    } else {
        baseUrl = context.api.getProjectBaseUrl('@current')
    }

    return { url: `${baseUrl}${substitute(params.url, params.params)}` }
}

export default (): ToolBase<typeof schema, AppUrlResult> => ({
    name: 'generate-app-url',
    schema,
    handler: generateAppUrlHandler,
})
