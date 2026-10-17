import type { CachedOrg, CachedProject } from '@/tools/types'

/** Bounds the onboarded-products line for intent-heavy teams; the environment
 *  prompt is repeated context, so the tail is summarized as a count instead. */
const MAX_ONBOARDED_PRODUCTS = 12

/**
 * Per-product enablement facts for the active project, so an agent knows which
 * PostHog products it can rely on (and which are off) without calling
 * `project-get` and interpreting a raw settings payload. Facts only, stated
 * neutrally: whether to recommend enabling something is the agent's call.
 */
function buildProductLines(project: CachedProject): string[] {
    // Only flag-backed products get an enabled/not-enabled verdict, because their
    // Team opt-in is an authoritative on/off switch. Products with no such switch
    // (feature flags, experiments, ...) are reported via completed onboarding below.
    const optIns = [
        { label: 'session replay', enabled: project.session_recording_opt_in },
        { label: 'exception autocapture (error tracking)', enabled: project.autocapture_exceptions_opt_in },
        { label: 'surveys', enabled: project.surveys_opt_in },
        { label: 'heatmaps', enabled: project.heatmaps_opt_in },
    ]
    const lines: string[] = []
    const enabled = optIns.filter((p) => p.enabled === true).map((p) => p.label)
    const notEnabled = optIns.filter((p) => p.enabled !== true).map((p) => p.label)
    if (enabled.length > 0) {
        lines.push(`Products enabled in this project: ${enabled.join(', ')}.`)
    }
    if (notEnabled.length > 0) {
        lines.push(`Products not enabled: ${notEnabled.join(', ')}.`)
    }
    // Intent rows without `onboarding_completed_at` can be a single abandoned
    // click, so only completed onboarding counts as "set up".
    const onboarded = [
        ...new Set(
            (project.product_intents ?? [])
                .filter((intent) => intent.onboarding_completed_at && intent.product_type)
                .map((intent) => (intent.product_type as string).replace(/_/g, ' '))
        ),
    ].sort()
    if (onboarded.length > 0) {
        const shown = onboarded.slice(0, MAX_ONBOARDED_PRODUCTS)
        const more = onboarded.length - shown.length
        lines.push(`Products set up (onboarding completed): ${shown.join(', ')}${more > 0 ? ` (+${more} more)` : ''}.`)
    }
    return lines
}

/**
 * `undefined` means unknown (key lacks `integration:read`, or the fetch failed):
 * say nothing rather than a false "none". An empty list is a real answer and is
 * rendered, since "no integrations connected" is itself useful to an agent.
 */
function buildIntegrationsLine(integrationKinds?: string[]): string | undefined {
    if (!integrationKinds) {
        return undefined
    }
    if (integrationKinds.length === 0) {
        return 'Integrations connected: none.'
    }
    return `Integrations connected: ${[...new Set(integrationKinds)].sort().join(', ')}.`
}

export interface EnvironmentContextOptions {
    /** Integration kinds connected in the active project; `undefined` means unknown. */
    integrationKinds?: string[]
}

export function buildActiveEnvironmentContextPrompt(
    org?: CachedOrg,
    project?: CachedProject,
    regionalBaseUrl?: string,
    opts?: EnvironmentContextOptions
): string | undefined {
    if (!org && !project) {
        return undefined
    }
    const lines: string[] = []
    const projectName = project?.name ?? 'Unknown'
    const projectId = project?.id ?? 'unknown'
    if (org) {
        const orgName = org.name ?? 'Unknown'
        const orgId = org.id ?? 'unknown'
        lines.push(
            `You are currently in project "${projectName}" (id: ${projectId}) within organization "${orgName}" (id: ${orgId}).`
        )
    } else {
        lines.push(`You are currently in project "${projectName}" (id: ${projectId}).`)
    }
    if (regionalBaseUrl) {
        const origin = regionalBaseUrl.replace(/^https?:\/\//, '')
        lines.push(
            project?.id !== undefined
                ? `Base URL: ${origin} — add /project/${project.id} for project-scoped paths.`
                : `Base URL: ${origin}.`
        )
    }
    if (project) {
        lines.push('For project settings such as the timezone, call `project-get` without an ID.')
        if (project.test_account_filters_default_checked) {
            lines.push(
                'This project filters out internal and test users by default. `query-*` tools apply this automatically when `filterTestAccounts` is omitted; when composing queries for other tools (e.g. insight-create), set `filterTestAccounts: true` unless the user asks to include internal/test data.'
            )
        }
        const poeValue = project.person_on_events_querying_enabled as string | boolean | null | undefined
        if (poeValue === true || poeValue === 'true') {
            lines.push(
                'Person-on-events mode is enabled. When querying `person.properties.*` on the events table, values reflect what was set at the time the event was ingested, not the person\'s current value. The same person can have different property values across different events. Do not suggest workarounds for "query-time" person properties.'
            )
        } else {
            lines.push(
                "Person properties are query-time in this project. `person.properties.*` on the events table always returns the person's current (latest) value, regardless of when the event occurred."
            )
        }
        lines.push(...buildProductLines(project))
        const integrationsLine = buildIntegrationsLine(opts?.integrationKinds)
        if (integrationsLine) {
            lines.push(integrationsLine)
        }
    }
    // No prose preamble: the heading plus the lines themselves already say the agent
    // is in this project, and the sentence it replaced ("All tool calls and queries
    // default to this environment…") cost 111 characters of a budgeted payload to
    // restate that.
    return `### Active environment\n\n${lines.join('\n')}`
}

/**
 * The tools the MCP actually advertises in single-exec mode. Without this the domain
 * index is the only list in the payload, and it names PostHog resources rather than
 * callable tools — so a model that reads `scout|survey|…` as the tool list has no
 * callable name to reach for. `render-ui` is listed only where it is mounted.
 */
export function buildAvailableToolsBlock(renderUiEnabled?: boolean): string {
    const lines = ['exec – run any PostHog command; its `command` description has the syntax.']
    if (renderUiEnabled) {
        lines.push('render-ui – show a tool result as an interactive app.')
    }
    return lines.join('\n')
}

export { buildToolDomainsBlock, buildToolDomainsCompact, ToolDomainExtractor } from './tool-domains'
export type { ToolInfo } from './tool-domains'

export interface QueryToolInfo {
    name: string
    title: string
    systemPromptHint?: string
}

/**
 * Renders the `query-*` tool catalog injected into the system prompt as a
 * single bullet list. Populated from the YAML `system_prompt_hint` field with
 * `title` as a fallback so a missing hint is visible rather than silent.
 */
export class QueryToolCatalog {
    constructor(private readonly tools: QueryToolInfo[]) {}

    toMarkdown(): string {
        const queryTools = this.filteredAndSorted()
        if (queryTools.length === 0) {
            return ''
        }
        return queryTools.map((t) => `- \`${t.name}\` — ${t.systemPromptHint ?? t.title}`).join('\n')
    }

    private filteredAndSorted(): QueryToolInfo[] {
        return this.tools.filter((t) => t.name.startsWith('query-')).sort((a, b) => a.name.localeCompare(b.name))
    }
}

export function buildQueryToolsBlock(tools: QueryToolInfo[]): string {
    return new QueryToolCatalog(tools).toMarkdown()
}
