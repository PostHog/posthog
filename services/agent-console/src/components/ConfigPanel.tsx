/**
 * `<ConfigPanel />` — structured rendering of an agent revision's spec.
 *
 * Optimized for agents with lots of capabilities (concierge has 17 tools,
 * 13 skills, and an MCP that fans out to 46 curated sub-tools). The
 * layout:
 *   - Top-level summary chip row + a global filter for tools/MCP tools/skills.
 *   - Tools are sub-grouped by kind (native / client / custom) — each
 *     group is its own collapsible card with a 2-col card grid inside.
 *   - MCPs expose their curated sub-tool list inline with approval markers.
 *   - Skills render as a 2-col card grid with truncated descriptions.
 *   - Integrations + Secrets and Limits + Auth share two-column rows
 *     to claw vertical space back.
 *
 * Click behaviour: custom tool cards + skill cards open the bundle file
 * via `onSelectBundleFile`. Native + client tool cards open a detail
 * dialog (description + args/returns/requires, sourced from the runner's
 * native-tool catalog and the client tool's own `args_schema`).
 *
 * `highlightedSection` lets the dock's `focus_spec_section` client tool
 * draw an info-coloured ring around one section so the user can tell
 * which one the agent just steered them to.
 */

'use client'

import {
    CalendarClockIcon,
    ChevronDownIcon,
    ChevronRightIcon,
    CodeIcon,
    GlobeIcon,
    HashIcon,
    InfoIcon,
    KeyIcon,
    LinkIcon,
    LockIcon,
    MessageSquareIcon,
    PuzzleIcon,
    SearchIcon,
    ServerIcon,
    ShieldIcon,
    SparklesIcon,
    TimerIcon,
    UserIcon,
    WebhookIcon,
    WrenchIcon,
    ZapIcon,
} from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'

import { JsonView } from '@posthog/agent-chat'
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@posthog/quill'

import type { NativeToolCatalogEntry } from '@/lib/apiClient'
import type { McpRef } from '@/types/mcp'

import { EditWithAIButton } from './EditWithAIButton'

/* ── Spec subset types ──────────────────────────────────────────── */

interface NativeToolRef {
    kind: 'native'
    id: string
}
interface CustomToolRef {
    kind: 'custom'
    id: string
    path: string
}
interface CustomTemplateToolRef {
    kind: 'custom_template'
    id: string
    from_template: string
}
interface ClientToolRef {
    kind: 'client'
    id: string
    description?: string
    args_schema?: unknown
}
type ToolRef = NativeToolRef | CustomToolRef | CustomTemplateToolRef | ClientToolRef

interface SkillRef {
    id: string
    path: string
    description?: string
}

interface Trigger {
    type: string
    config?: Record<string, unknown>
}

interface Limits {
    max_turns?: number
    max_tool_calls?: number
    max_wall_seconds?: number
}

interface McpToolEntry {
    name: string
    requires_approval?: boolean
}

export type HighlightedSection = 'triggers' | 'tools' | 'skills' | 'secrets' | 'limits' | 'mcps' | null

export interface ConfigPanelProps {
    spec: Record<string, unknown>
    /** Highlighted section — used by the dock's `focus_spec_section` flow. */
    highlightedSection?: HighlightedSection
    /** Native-tool catalog — required for the native-tool detail dialog. */
    nativeToolCatalog?: NativeToolCatalogEntry[]
    /** Navigate to a file inside the revision's bundle. Wired to custom-tool + skill cards. */
    onSelectBundleFile?: (path: string) => void
    /** When provided, each editable section gets an "Edit with AI" pill. */
    agentSlug?: string
    /**
     * Controlled filter — when set (alongside `onFilterChange`), the panel
     * stops rendering its own search input and uses the parent's value
     * instead. Use when the host page wants the filter to live in its
     * header (e.g. the `<ConfigPanelCard>` toolbar in `RevisionsBrowser`).
     */
    filter?: string
    onFilterChange?: (next: string) => void
}

const EXPAND_THRESHOLD = 6

export function ConfigPanel({
    spec,
    highlightedSection,
    nativeToolCatalog,
    onSelectBundleFile,
    agentSlug,
    filter,
    onFilterChange,
}: ConfigPanelProps): React.ReactElement {
    const model = typeof spec.model === 'string' ? spec.model : undefined
    const reasoning = typeof spec.reasoning === 'string' ? spec.reasoning : undefined
    const entrypoint = typeof spec.entrypoint === 'string' ? spec.entrypoint : undefined
    const triggers = Array.isArray(spec.triggers) ? (spec.triggers as Trigger[]) : []
    const tools = Array.isArray(spec.tools) ? (spec.tools as ToolRef[]) : []
    const mcps = Array.isArray(spec.mcps) ? (spec.mcps as McpRef[]) : []
    const skills = Array.isArray(spec.skills) ? (spec.skills as SkillRef[]) : []
    const integrations = Array.isArray(spec.integrations) ? (spec.integrations as string[]) : []
    const secrets = Array.isArray(spec.secrets) ? (spec.secrets as string[]) : []
    const limits = (spec.limits && typeof spec.limits === 'object' ? spec.limits : {}) as Limits
    const auth = (spec.auth && typeof spec.auth === 'object' ? spec.auth : {}) as {
        modes?: Array<{ type: string }>
        mode?: string
    }

    const isFilterControlled = filter !== undefined && onFilterChange !== undefined
    const [internalFilter, setInternalFilter] = useState('')
    const globalFilter = isFilterControlled ? filter : internalFilter
    const setGlobalFilter = isFilterControlled ? onFilterChange : setInternalFilter
    const [openTool, setOpenTool] = useState<{ kind: 'native' | 'client'; ref: ToolRef } | null>(null)

    const toolsByKind = groupToolsByKind(tools)
    const mcpToolCount = mcps.reduce((sum, m) => sum + normalizeMcpTools(m).length, 0)

    const editAction = (section: string): React.ReactElement | undefined => {
        if (!agentSlug) {
            return undefined
        }
        return (
            <EditWithAIButton
                prompt={`Help me edit the \`${section}\` for \`${agentSlug}\`.`}
                agentSlug={agentSlug}
                label="Edit"
                compact
            />
        )
    }

    return (
        <div className="divide-y divide-border/60">
            {/* Filter row: only rendered when the panel owns its own filter state.
             *  When the host page lifts the filter into its own toolbar (e.g.
             *  `<ConfigPanelCard>` in `RevisionsBrowser`), we drop this row to
             *  avoid duplicating the input. */}
            {!isFilterControlled ? (
                <div className="flex items-center gap-2 px-3 py-1.5">
                    <SearchIcon className="h-3.5 w-3.5 text-muted-foreground" />
                    <input
                        value={globalFilter}
                        onChange={(e) => setGlobalFilter(e.target.value)}
                        placeholder="Filter tools, MCP tools, skills…"
                        className="w-full bg-transparent text-sm placeholder:text-muted-foreground/70 focus:outline-none"
                    />
                    {globalFilter ? (
                        <button
                            type="button"
                            onClick={() => setGlobalFilter('')}
                            className="text-[0.625rem] uppercase tracking-wide text-muted-foreground hover:text-foreground"
                        >
                            clear
                        </button>
                    ) : null}
                </div>
            ) : null}

            {/* ── Model ─── */}
            <Section
                icon={<SparklesIcon className="h-3 w-3" />}
                label="Model"
                info="The LLM the runner sends every request to. `reasoning` controls how much extended-thinking budget the model is allowed — `high` for tasks that need careful planning, `low` for simple lookups, omit for the model's default."
                action={editAction('model')}
            >
                {model ? (
                    <div className="flex flex-wrap items-center gap-1.5">
                        <Chip>{model}</Chip>
                        {reasoning ? (
                            <span className="text-[0.6875rem] text-muted-foreground">
                                reasoning <span className="font-mono text-foreground">{reasoning}</span>
                            </span>
                        ) : null}
                    </div>
                ) : (
                    <Empty />
                )}
            </Section>

            {/* ── Triggers ─── */}
            <Section
                icon={<ZapIcon className="h-3 w-3" />}
                label="Triggers"
                count={triggers.length}
                highlighted={highlightedSection === 'triggers'}
                info="What can start a session of this agent — cron schedules, chat messages, webhooks, Slack mentions, MCP transport."
                action={editAction('triggers')}
            >
                {triggers.length === 0 ? (
                    <Empty />
                ) : (
                    <div className="flex flex-col gap-1.5">
                        {triggers.map((t, i) => (
                            <TriggerRow key={i} trigger={t} />
                        ))}
                    </div>
                )}
            </Section>

            {/* ── Tools (grouped by kind) ─── */}
            <Section
                icon={<WrenchIcon className="h-3 w-3" />}
                label="Tools"
                count={tools.length}
                highlighted={highlightedSection === 'tools'}
                info="Callable functions the agent has direct access to. Grouped by kind — open each group's info pill for what that kind means."
                action={editAction('tools')}
            >
                {tools.length === 0 ? (
                    <Empty label="No tools" />
                ) : (
                    <div className="flex flex-col gap-2">
                        {(['native', 'client', 'custom', 'custom_template'] as const).map((kind) => {
                            const list = toolsByKind[kind]
                            if (!list || list.length === 0) {
                                return null
                            }
                            return (
                                <ToolGroup
                                    key={kind}
                                    kind={kind}
                                    tools={list}
                                    filter={globalFilter}
                                    onSelectBundleFile={onSelectBundleFile}
                                    onNativeClick={(ref) => setOpenTool({ kind: 'native', ref })}
                                    onClientClick={(ref) => setOpenTool({ kind: 'client', ref })}
                                />
                            )
                        })}
                    </div>
                )}
            </Section>

            {/* ── MCPs ─── */}
            <Section
                icon={<ServerIcon className="h-3 w-3" />}
                label="MCPs"
                count={mcps.length}
                countHint={mcpToolCount ? `${mcpToolCount} tools` : undefined}
                highlighted={highlightedSection === 'mcps'}
                info="Remote MCP servers the agent connects to during a session. Each entry exposes a curated tool list; tools marked with a lock require approval before they can run."
                action={editAction('mcps')}
            >
                {mcps.length === 0 ? (
                    <Empty label="None connected" />
                ) : (
                    <div className="flex flex-col gap-2">
                        {mcps.map((m, i) => (
                            <McpCard key={i} mcp={m} filter={globalFilter} />
                        ))}
                    </div>
                )}
            </Section>

            {/* ── Skills ─── */}
            <Section
                icon={<PuzzleIcon className="h-3 w-3" />}
                label="Skills"
                count={skills.length}
                highlighted={highlightedSection === 'skills'}
                info="Markdown reference material the agent can load on demand via `@posthog/load-skill`. Loaded lazily — the system prompt only lists them; the bodies cost tokens only when the agent decides to read one."
                action={editAction('skills')}
            >
                {skills.length === 0 ? (
                    <Empty label="None loaded" />
                ) : (
                    <SkillGrid skills={skills} filter={globalFilter} onClick={onSelectBundleFile} />
                )}
            </Section>

            {/* ── Integrations ─── */}
            <Section
                icon={<LinkIcon className="h-3 w-3" />}
                label="Integrations"
                count={integrations.length}
                info="OAuth integrations the agent's tools rely on. Listed here so the runner can check connection status before starting a session."
                action={editAction('integrations')}
            >
                {integrations.length === 0 ? (
                    <Empty label="None required" />
                ) : (
                    <div className="flex flex-wrap gap-1.5">
                        {integrations.map((i) => (
                            <Chip key={i}>{i}</Chip>
                        ))}
                    </div>
                )}
            </Section>

            {/* ── Secrets ─── */}
            <Section
                icon={<KeyIcon className="h-3 w-3" />}
                label="Secrets"
                count={secrets.length}
                highlighted={highlightedSection === 'secrets'}
                info="Env-variable names this agent reads from the encrypted env block. Values are never displayed — set them via the connections tab or the dock's `set_secret` tool."
                action={editAction('secrets')}
            >
                {secrets.length === 0 ? (
                    <Empty label="None required" />
                ) : (
                    <div className="flex flex-wrap gap-1.5">
                        {secrets.map((s) => (
                            <Chip key={s}>{s}</Chip>
                        ))}
                    </div>
                )}
            </Section>

            {/* ── Limits ─── */}
            <Section
                icon={<TimerIcon className="h-3 w-3" />}
                label="Limits"
                highlighted={highlightedSection === 'limits'}
                info="Per-session safety caps the runner enforces. When any limit is hit the session ends with `max_*_reached` and the agent's last partial output is preserved."
                action={editAction('limits')}
            >
                {Object.keys(limits).length === 0 ? (
                    <Empty />
                ) : (
                    <div className="flex flex-wrap gap-3">
                        {limits.max_turns !== undefined ? (
                            <LimitStat label="turns" value={String(limits.max_turns)} />
                        ) : null}
                        {limits.max_tool_calls !== undefined ? (
                            <LimitStat label="tool calls" value={String(limits.max_tool_calls)} />
                        ) : null}
                        {limits.max_wall_seconds !== undefined ? (
                            <LimitStat label="wall" value={`${limits.max_wall_seconds}s`} />
                        ) : null}
                    </div>
                )}
            </Section>

            {/* ── Auth ─── */}
            <Section
                icon={<ShieldIcon className="h-3 w-3" />}
                label="Auth"
                info="How incoming triggers are authenticated. `oauth` and `pat` are end-user identities; `posthog_internal` is used when one PostHog service calls another."
            >
                {auth.modes && auth.modes.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                        {auth.modes.map((m, i) => (
                            <Chip key={i}>{m.type}</Chip>
                        ))}
                    </div>
                ) : auth.mode ? (
                    <Chip>{auth.mode}</Chip>
                ) : (
                    <Empty />
                )}
            </Section>

            {entrypoint && entrypoint !== 'agent.md' ? (
                <Section icon={<CodeIcon className="h-3 w-3" />} label="Entrypoint">
                    <Chip>{entrypoint}</Chip>
                </Section>
            ) : null}

            {openTool ? (
                <ToolDetailDialog
                    tool={openTool.ref}
                    kind={openTool.kind}
                    catalog={nativeToolCatalog}
                    onClose={() => setOpenTool(null)}
                />
            ) : null}
        </div>
    )
}

/* ── Section container ─────────────────────────────────────────── */

function Section({
    icon,
    label,
    count,
    countHint,
    highlighted,
    info,
    action,
    children,
}: {
    icon: ReactNode
    label: string
    count?: number
    countHint?: string
    highlighted?: boolean
    /** Optional one- or two-sentence description shown when the info toggle is open. */
    info?: ReactNode
    action?: ReactNode
    children: ReactNode
}): React.ReactElement {
    const [infoOpen, setInfoOpen] = useState(false)
    return (
        // Flat band, no card chrome. The host `<ConfigPanelCard>` already
        // provides the outer card; sections sit inside it as horizontal
        // strips divided by `divide-y` on the parent. Single `py-3 px-3`
        // gives each band the same top/bottom rhythm; inner pieces stack
        // with `space-y-2`.
        <div
            className={
                'relative' +
                (highlighted
                    ? ' bg-info/5 before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-info'
                    : '')
            }
        >
            <div className="space-y-2 px-3 py-3">
                <div className="flex items-center gap-2">
                    <span className="flex items-center gap-1.5 text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                        {icon}
                        {label}
                    </span>
                    {count !== undefined ? (
                        <span className="rounded-full bg-muted/40 px-1.5 py-0.5 font-mono text-[0.625rem] text-muted-foreground">
                            {count}
                            {countHint ? ` · ${countHint}` : ''}
                        </span>
                    ) : null}
                    <div className="ml-auto flex items-center gap-1">
                        {action ? <div>{action}</div> : null}
                        {info ? (
                            <button
                                type="button"
                                onClick={() => setInfoOpen((o) => !o)}
                                aria-pressed={infoOpen}
                                aria-label={infoOpen ? 'Hide section info' : 'Show section info'}
                                // On state uses primary so it's unmistakably "lit"
                                // and shares colour family with the info panel below.
                                className={
                                    'flex h-5 w-5 items-center justify-center rounded transition-colors ' +
                                    (infoOpen
                                        ? 'bg-primary text-primary-foreground shadow-sm'
                                        : 'text-muted-foreground hover:bg-muted hover:text-foreground')
                                }
                            >
                                <InfoIcon className="h-3 w-3" />
                            </button>
                        ) : null}
                    </div>
                </div>
                {info && infoOpen ? (
                    // Panel shares the primary palette with the active icon so
                    // the visual link is obvious — left-border accent reinforces
                    // that the panel "belongs to" the lit button above.
                    <div className="border-l-2 border-primary bg-primary/10 px-2.5 py-2 text-[0.75rem] leading-relaxed text-foreground/80">
                        {info}
                    </div>
                ) : null}
                <div>{children}</div>
            </div>
        </div>
    )
}

function Chip({ children, kind = 'default' }: { children: ReactNode; kind?: 'default' | 'muted' }): React.ReactElement {
    const className =
        kind === 'muted'
            ? 'inline-flex items-center gap-1 rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 font-mono text-[0.6875rem] text-muted-foreground'
            : 'inline-flex items-center gap-1 rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 font-mono text-[0.6875rem] text-muted-foreground'
    return <span className={className}>{children}</span>
}

function Empty({ label = 'Not set' }: { label?: string }): React.ReactElement {
    return <span className="text-xs italic text-muted-foreground">{label}</span>
}

function LimitStat({ label, value }: { label: string; value: string }): React.ReactElement {
    return (
        <span className="inline-flex items-baseline gap-1">
            <span className="font-mono text-sm font-medium text-foreground">{value}</span>
            <span className="text-[0.6875rem] text-muted-foreground">{label}</span>
        </span>
    )
}

/* ── Tools ──────────────────────────────────────────────────────── */

function groupToolsByKind(tools: ToolRef[]): Record<string, ToolRef[]> {
    const out: Record<string, ToolRef[]> = {}
    for (const t of tools) {
        ;(out[t.kind] ??= []).push(t)
    }
    return out
}

const TOOL_KIND_LABEL: Record<string, string> = {
    native: 'Native',
    client: 'Client-fulfilled',
    custom: 'Custom (bundle)',
    custom_template: 'Custom (template)',
}

const TOOL_KIND_INFO: Record<string, string> = {
    native: 'Server-side built-in tools provided by the runner. No setup required — every agent can call them.',
    client: 'Tools fulfilled by the host UI (e.g. the agent console). Only available when the user is interacting through a client that implements them; otherwise the call returns `unhandled_client_tool`.',
    custom: "Tool source.ts authored inside this agent's bundle and compiled at freeze time. Runs in a sandbox alongside the agent.",
    custom_template:
        'Tool pinned to a published version of a `@posthog/*` custom-tool template. The source lives in the shared template registry; the agent references it by name.',
}

function ToolGroup({
    kind,
    tools,
    filter,
    onSelectBundleFile,
    onNativeClick,
    onClientClick,
}: {
    kind: string
    tools: ToolRef[]
    filter: string
    onSelectBundleFile?: (path: string) => void
    onNativeClick: (ref: NativeToolRef) => void
    onClientClick: (ref: ClientToolRef) => void
}): React.ReactElement {
    const filtered = useMemo(
        () => (filter ? tools.filter((t) => t.id.toLowerCase().includes(filter.toLowerCase())) : tools),
        [tools, filter]
    )
    const startOpen = tools.length <= EXPAND_THRESHOLD || filter.length > 0
    const [open, setOpen] = useState(startOpen)
    const [infoOpen, setInfoOpen] = useState(false)
    const effectiveOpen = filter.length > 0 ? true : open
    const Icon =
        kind === 'client' ? UserIcon : kind === 'custom' || kind === 'custom_template' ? CodeIcon : SparklesIcon
    const info = TOOL_KIND_INFO[kind]

    return (
        // Flat group, indented inside the parent Tools section. No outer
        // card so the section reads as one continuous panel.
        <div>
            <div className="flex w-full items-center gap-2 py-1">
                <button
                    type="button"
                    onClick={() => setOpen((o) => !o)}
                    className="flex flex-1 items-center gap-2 text-left"
                >
                    {effectiveOpen ? (
                        <ChevronDownIcon className="h-3 w-3 text-muted-foreground" />
                    ) : (
                        <ChevronRightIcon className="h-3 w-3 text-muted-foreground" />
                    )}
                    <Icon className="h-3 w-3 text-muted-foreground" />
                    <span className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                        {TOOL_KIND_LABEL[kind] ?? kind}
                    </span>
                    <span className="rounded-full bg-muted/40 px-1.5 py-0.5 font-mono text-[0.625rem] text-muted-foreground">
                        {filter ? `${filtered.length}/${tools.length}` : tools.length}
                    </span>
                </button>
                {info ? (
                    <button
                        type="button"
                        onClick={() => setInfoOpen((o) => !o)}
                        aria-pressed={infoOpen}
                        aria-label={infoOpen ? 'Hide kind info' : 'Show kind info'}
                        className={
                            'flex h-5 w-5 items-center justify-center rounded transition-colors ' +
                            (infoOpen
                                ? 'bg-primary text-primary-foreground shadow-sm'
                                : 'text-muted-foreground hover:bg-muted hover:text-foreground')
                        }
                    >
                        <InfoIcon className="h-3 w-3" />
                    </button>
                ) : null}
            </div>
            {info && infoOpen ? (
                <div className="mt-1 border-l-2 border-primary bg-primary/10 px-3 py-2 text-[0.75rem] leading-relaxed text-foreground/80">
                    {info}
                </div>
            ) : null}
            {effectiveOpen ? (
                <div className="mt-1.5 grid grid-cols-1 gap-1.5 md:grid-cols-2">
                    {filtered.map((t, i) => (
                        <ToolCard
                            key={`${t.kind}:${t.id}:${i}`}
                            tool={t}
                            onSelectBundleFile={onSelectBundleFile}
                            onNativeClick={onNativeClick}
                            onClientClick={onClientClick}
                        />
                    ))}
                    {filtered.length === 0 ? (
                        <div className="col-span-full text-xs italic text-muted-foreground">No matches.</div>
                    ) : null}
                </div>
            ) : null}
        </div>
    )
}

function ToolCard({
    tool,
    onSelectBundleFile,
    onNativeClick,
    onClientClick,
}: {
    tool: ToolRef
    onSelectBundleFile?: (path: string) => void
    onNativeClick: (ref: NativeToolRef) => void
    onClientClick: (ref: ClientToolRef) => void
}): React.ReactElement {
    const desc =
        tool.kind === 'client'
            ? tool.description
            : tool.kind === 'custom'
              ? `→ ${tool.path}`
              : tool.kind === 'custom_template'
                ? `from ${tool.from_template}`
                : undefined
    const onClick =
        tool.kind === 'native'
            ? (): void => onNativeClick(tool)
            : tool.kind === 'client'
              ? (): void => onClientClick(tool)
              : tool.kind === 'custom' && onSelectBundleFile
                ? (): void => onSelectBundleFile(tool.path)
                : undefined
    const inner = (
        <>
            <code className="block truncate font-mono text-[0.6875rem] text-foreground">{stripNamespace(tool.id)}</code>
            {desc ? (
                <div className="mt-0.5 line-clamp-2 text-[0.6875rem] leading-snug text-muted-foreground">{desc}</div>
            ) : null}
        </>
    )
    if (onClick) {
        return (
            <button
                type="button"
                onClick={onClick}
                className="rounded border border-border/60 bg-card px-2 py-1.5 text-left transition-colors hover:border-border hover:bg-accent/40"
            >
                {inner}
            </button>
        )
    }
    return <div className="rounded border border-border/60 bg-card px-2 py-1.5">{inner}</div>
}

/** "@posthog/agent-applications-list" → "agent-applications-list" for cards. */
function stripNamespace(id: string): string {
    const slash = id.indexOf('/')
    return slash === -1 ? id : id.slice(slash + 1)
}

/* ── MCPs ───────────────────────────────────────────────────────── */

function normalizeMcpTools(mcp: McpRef): McpToolEntry[] {
    const raw = (mcp as unknown as { tools?: Array<string | McpToolEntry> }).tools ?? []
    return raw.map((t) => (typeof t === 'string' ? { name: t } : t))
}

function McpCard({ mcp, filter }: { mcp: McpRef; filter: string }): React.ReactElement {
    const mcpTools = useMemo(() => normalizeMcpTools(mcp), [mcp])
    const filtered = useMemo(
        () => (filter ? mcpTools.filter((t) => t.name.toLowerCase().includes(filter.toLowerCase())) : mcpTools),
        [mcpTools, filter]
    )
    const startOpen = mcpTools.length <= EXPAND_THRESHOLD || filter.length > 0
    const [open, setOpen] = useState(startOpen)
    const effectiveOpen = filter.length > 0 ? true : open
    const approvalCount = mcpTools.filter((t) => t.requires_approval).length
    const id = (mcp as unknown as { id?: string }).id

    return (
        <div className="rounded-md border border-border/60 bg-muted/10">
            <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-muted/30"
            >
                {effectiveOpen ? (
                    <ChevronDownIcon className="h-3 w-3 text-muted-foreground" />
                ) : (
                    <ChevronRightIcon className="h-3 w-3 text-muted-foreground" />
                )}
                <ServerIcon className="h-3 w-3 text-muted-foreground" />
                <span className="font-mono text-[0.6875rem] text-foreground">{id ?? mcp.url}</span>
                <span className="rounded-full bg-muted/40 px-1.5 py-0.5 font-mono text-[0.625rem] text-muted-foreground">
                    {filter ? `${filtered.length}/${mcpTools.length}` : `${mcpTools.length} tools`}
                </span>
                {approvalCount > 0 ? (
                    <span className="inline-flex items-center gap-0.5 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[0.625rem] text-amber-700 dark:text-amber-300">
                        <LockIcon className="h-2.5 w-2.5" />
                        {approvalCount} requires approval
                    </span>
                ) : null}
                <span className="ml-auto truncate font-mono text-[0.625rem] text-muted-foreground/70">{mcp.url}</span>
            </button>
            {effectiveOpen ? (
                <div className="grid grid-cols-1 gap-1.5 p-2 md:grid-cols-2">
                    {filtered.map((t) => (
                        <div
                            key={t.name}
                            className="flex items-center gap-1.5 rounded border border-border/60 bg-card px-2 py-1"
                        >
                            <code className="flex-1 truncate font-mono text-[0.6875rem] text-foreground">{t.name}</code>
                            {t.requires_approval ? (
                                <LockIcon className="h-3 w-3 shrink-0 text-amber-600 dark:text-amber-300" />
                            ) : null}
                        </div>
                    ))}
                    {filtered.length === 0 ? (
                        <div className="col-span-full text-xs italic text-muted-foreground">No matches.</div>
                    ) : null}
                </div>
            ) : null}
        </div>
    )
}

/* ── Skills ─────────────────────────────────────────────────────── */

function SkillGrid({
    skills,
    filter,
    onClick,
}: {
    skills: SkillRef[]
    filter: string
    onClick?: (path: string) => void
}): React.ReactElement {
    const filtered = useMemo(
        () =>
            filter
                ? skills.filter(
                      (s) =>
                          s.id.toLowerCase().includes(filter.toLowerCase()) ||
                          (s.description ?? '').toLowerCase().includes(filter.toLowerCase())
                  )
                : skills,
        [skills, filter]
    )
    if (filtered.length === 0) {
        return <div className="text-xs italic text-muted-foreground">No matches.</div>
    }
    return (
        <div className="grid grid-cols-1 gap-1.5 md:grid-cols-2">
            {filtered.map((s) => (
                <SkillCard key={s.id} skill={s} onClick={onClick} />
            ))}
        </div>
    )
}

function SkillCard({ skill, onClick }: { skill: SkillRef; onClick?: (path: string) => void }): React.ReactElement {
    const inner = (
        <>
            <code className="block truncate font-mono text-[0.6875rem] text-foreground">{skill.id}</code>
            {skill.description ? (
                <div
                    className="mt-0.5 line-clamp-2 text-[0.6875rem] leading-snug text-muted-foreground"
                    title={skill.description}
                >
                    {skill.description}
                </div>
            ) : (
                <div className="mt-0.5 font-mono text-[0.625rem] text-muted-foreground/70">{skill.path}</div>
            )}
        </>
    )
    if (onClick) {
        return (
            <button
                type="button"
                onClick={() => onClick(skill.path)}
                className="rounded border border-border/60 bg-card px-2 py-1.5 text-left transition-colors hover:border-border hover:bg-accent/40"
            >
                {inner}
            </button>
        )
    }
    return <div className="rounded border border-border/60 bg-card px-2 py-1.5">{inner}</div>
}

/* ── Triggers ───────────────────────────────────────────────────── */

function TriggerRow({ trigger }: { trigger: Trigger }): React.ReactElement {
    const { Icon, summary, detail } = describeTrigger(trigger)
    return (
        <div className="flex items-start gap-2 rounded-md border border-border/60 bg-card px-2.5 py-1.5">
            <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 text-xs">
                    <span className="font-medium text-foreground">{trigger.type}</span>
                    <span className="truncate text-muted-foreground">{summary}</span>
                </div>
                {detail ? (
                    <div className="mt-0.5 font-mono text-[0.6875rem] text-muted-foreground">{detail}</div>
                ) : null}
            </div>
        </div>
    )
}

function describeTrigger(trigger: Trigger): { Icon: typeof CalendarClockIcon; summary: string; detail?: string } {
    const cfg = trigger.config ?? {}
    switch (trigger.type) {
        case 'cron':
            return {
                Icon: CalendarClockIcon,
                summary: typeof cfg.schedule === 'string' ? cfg.schedule : 'on schedule',
                detail: typeof cfg.timezone === 'string' ? cfg.timezone : undefined,
            }
        case 'slack':
            return {
                Icon: MessageSquareIcon,
                summary: Array.isArray(cfg.trusted_workspaces)
                    ? `workspaces: ${(cfg.trusted_workspaces as string[]).join(', ')}`
                    : 'on mention',
            }
        case 'webhook':
            return {
                Icon: WebhookIcon,
                summary: typeof cfg.path === 'string' ? cfg.path : 'on POST',
            }
        case 'chat':
            return { Icon: HashIcon, summary: 'on chat message' }
        case 'mcp':
            return { Icon: ServerIcon, summary: 'via MCP transport' }
        default:
            return { Icon: GlobeIcon, summary: '' }
    }
}

/* ── Tool detail dialog ─────────────────────────────────────────── */

function ToolDetailDialog({
    tool,
    kind,
    catalog,
    onClose,
}: {
    tool: ToolRef
    kind: 'native' | 'client'
    catalog?: NativeToolCatalogEntry[]
    onClose: () => void
}): React.ReactElement {
    const native = kind === 'native' && tool.kind === 'native' ? catalog?.find((e) => e.id === tool.id) : undefined
    const description =
        kind === 'client' && tool.kind === 'client' ? (tool.description ?? '') : (native?.schema.description ?? '')
    const args = kind === 'client' && tool.kind === 'client' ? tool.args_schema : native?.schema.args
    const returns = native?.schema.returns
    const requires = native?.schema.requires
    const costHint = native?.schema.cost_hint
    const sourceHint =
        kind === 'native' && !native
            ? 'Native tool catalog not loaded — details unavailable until /agent_native_tools/ resolves.'
            : null

    return (
        <Dialog open onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle className="font-mono text-sm">{tool.id}</DialogTitle>
                    <DialogDescription className="flex items-center gap-2 text-xs">
                        <Chip kind="muted">{kind}</Chip>
                        {costHint ? <Chip kind="muted">{costHint}</Chip> : null}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody render={<div />} className="space-y-4 py-4 text-sm">
                    {sourceHint ? (
                        <p className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                            {sourceHint}
                        </p>
                    ) : null}
                    {description ? <p className="text-foreground/90">{description}</p> : null}
                    {requires && (requires.integrations.length > 0 || requires.scopes.length > 0) ? (
                        <div className="space-y-1.5">
                            <h4 className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">Requires</h4>
                            <div className="flex flex-wrap gap-1.5 text-xs">
                                {requires.integrations.map((i) => (
                                    <Chip key={`int:${i}`} kind="muted">
                                        integration: {i}
                                    </Chip>
                                ))}
                                {requires.scopes.map((s) => (
                                    <Chip key={`scope:${s}`} kind="muted">
                                        scope: {s}
                                    </Chip>
                                ))}
                            </div>
                        </div>
                    ) : null}
                    {args ? (
                        <div className="space-y-1.5">
                            <h4 className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                                Arguments
                            </h4>
                            <div className="rounded-md border border-border bg-muted/20 p-2">
                                <JsonView value={args} expandToLevel={2} />
                            </div>
                        </div>
                    ) : null}
                    {returns ? (
                        <div className="space-y-1.5">
                            <h4 className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">Returns</h4>
                            <div className="rounded-md border border-border bg-muted/20 p-2">
                                <JsonView value={returns} expandToLevel={1} />
                            </div>
                        </div>
                    ) : null}
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}

/* ── Unstructured spec fields ───────────────────────────────────── */

/**
 * Escape hatch for spec fields we haven't built structured renderers
 * for yet — shows them as a labeled JsonView so we never silently drop
 * data the user might care about. Rendered as a flat band so it
 * continues the `divide-y` rhythm of the panel's other sections.
 */
export function UnstructuredFields({
    spec,
    knownKeys,
}: {
    spec: Record<string, unknown>
    knownKeys: string[]
}): React.ReactElement | null {
    const extras: Record<string, unknown> = {}
    for (const key of Object.keys(spec)) {
        if (!knownKeys.includes(key)) {
            extras[key] = spec[key]
        }
    }
    if (Object.keys(extras).length === 0) {
        return null
    }
    return (
        <div className="space-y-2 border-t border-border/60 px-3 py-3">
            <div className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">Other spec fields</div>
            <JsonView value={extras} expandToLevel={1} />
        </div>
    )
}

export const KNOWN_SPEC_KEYS = [
    'model',
    'triggers',
    'tools',
    'mcps',
    'skills',
    'integrations',
    'secrets',
    'limits',
    'entrypoint',
    'auth',
    'resume',
    'reasoning',
]
