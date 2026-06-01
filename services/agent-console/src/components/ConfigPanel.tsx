/**
 * `<ConfigPanel />` — structured rendering of an agent revision's spec.
 *
 * Covers the "knobs" of the spec: model, triggers, tools, mcps, skills,
 * integrations, secrets, limits, auth. The bundle (agent.md + skill
 * markdown + custom tool source) renders as a filesystem elsewhere;
 * clickable rows here cross-link into it.
 *
 * Native tool rows open a detail dialog with description + args schema
 * pulled from the runner's catalog (`/agent_native_tools/`). When a
 * shared Skills / Tools store ships, the dialog action will pop out to
 * that catalog.
 */

'use client'

import {
    CalendarClockIcon,
    CodeIcon,
    GlobeIcon,
    HashIcon,
    KeyIcon,
    LinkIcon,
    MessageSquareIcon,
    PuzzleIcon,
    ServerIcon,
    ShieldIcon,
    SparklesIcon,
    TimerIcon,
    WebhookIcon,
    WrenchIcon,
    ZapIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { JsonView } from '@posthog/agent-chat'
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@posthog/quill'

import type { NativeToolCatalogEntry } from '@/lib/apiClient'

export interface ConfigPanelProps {
    spec: Record<string, unknown>
    /**
     * Highlighted section — currently used for the in-page anchor /
     * scroll target when the dock's focus call lands on a spec section.
     */
    highlightedSection?: 'triggers' | 'tools' | 'skills' | 'secrets' | 'limits' | null
    /**
     * Optional native-tool catalog (from `/agent_native_tools/`). When
     * provided, clicking a native tool row opens a detail dialog with
     * its description + args schema.
     */
    nativeToolCatalog?: NativeToolCatalogEntry[]
    /**
     * Navigate to a file inside the revision's bundle. Wired to custom
     * tool rows (`path` from spec.tools) and skill rows (`path` from
     * spec.skills).
     */
    onSelectBundleFile?: (path: string) => void
}

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

interface AgentMcpRef {
    kind: 'agent'
    slug: string
}
interface ExternalMcpRef {
    kind: 'external'
    url: string
    auth?: { integration?: string }
}
type McpRef = AgentMcpRef | ExternalMcpRef

interface Trigger {
    type: string
    config?: Record<string, unknown>
}

interface Limits {
    max_turns?: number
    max_tool_calls?: number
    max_wall_seconds?: number
}

interface Auth {
    mode?: string
}

export function ConfigPanel({
    spec,
    highlightedSection,
    nativeToolCatalog,
    onSelectBundleFile,
}: ConfigPanelProps): React.ReactElement {
    const model = typeof spec.model === 'string' ? spec.model : undefined
    const triggers = Array.isArray(spec.triggers) ? (spec.triggers as Trigger[]) : []
    const tools = Array.isArray(spec.tools) ? (spec.tools as ToolRef[]) : []
    const mcps = Array.isArray(spec.mcps) ? (spec.mcps as McpRef[]) : []
    const skills = Array.isArray(spec.skills) ? (spec.skills as SkillRef[]) : []
    const integrations = Array.isArray(spec.integrations) ? (spec.integrations as string[]) : []
    const secrets = Array.isArray(spec.secrets) ? (spec.secrets as string[]) : []
    const limits = (spec.limits && typeof spec.limits === 'object' ? spec.limits : {}) as Limits
    const auth = (spec.auth && typeof spec.auth === 'object' ? spec.auth : {}) as Auth
    const reasoning = typeof spec.reasoning === 'string' ? spec.reasoning : undefined
    const entrypoint = typeof spec.entrypoint === 'string' ? spec.entrypoint : undefined

    const [openTool, setOpenTool] = useState<{ kind: 'native' | 'client'; ref: ToolRef } | null>(null)

    return (
        <div className="space-y-3">
            <Row label="Model" icon={<SparklesIcon className="h-3 w-3" />}>
                {model ? <Chip>{model}</Chip> : <Empty />}
            </Row>

            <Row
                label="Triggers"
                icon={<ZapIcon className="h-3 w-3" />}
                highlighted={highlightedSection === 'triggers'}
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
            </Row>

            <Row label="Tools" icon={<WrenchIcon className="h-3 w-3" />} highlighted={highlightedSection === 'tools'}>
                {tools.length === 0 ? (
                    <Empty label="No tools" />
                ) : (
                    <div className="flex flex-col gap-1.5">
                        {tools.map((t, i) => (
                            <ToolRow
                                key={`${t.kind}:${t.id}:${i}`}
                                tool={t}
                                onNativeClick={(ref) => setOpenTool({ kind: 'native', ref })}
                                onClientClick={(ref) => setOpenTool({ kind: 'client', ref })}
                                onCustomClick={(path) => onSelectBundleFile?.(path)}
                            />
                        ))}
                    </div>
                )}
            </Row>

            <Row label="MCPs" icon={<ServerIcon className="h-3 w-3" />}>
                {mcps.length === 0 ? (
                    <Empty label="None connected" />
                ) : (
                    <div className="flex flex-col gap-1.5">
                        {mcps.map((m, i) => (
                            <McpRow key={i} mcp={m} />
                        ))}
                    </div>
                )}
            </Row>

            <Row label="Skills" icon={<PuzzleIcon className="h-3 w-3" />} highlighted={highlightedSection === 'skills'}>
                {skills.length === 0 ? (
                    <Empty label="None loaded" />
                ) : (
                    <div className="flex flex-col gap-1.5">
                        {skills.map((s) => (
                            <SkillRow key={s.id} skill={s} onClick={onSelectBundleFile} />
                        ))}
                    </div>
                )}
            </Row>

            <Row label="Integrations" icon={<LinkIcon className="h-3 w-3" />}>
                {integrations.length === 0 ? (
                    <Empty label="None required" />
                ) : (
                    <div className="flex flex-wrap gap-1.5">
                        {integrations.map((i) => (
                            <Chip key={i} kind="muted">
                                {i}
                            </Chip>
                        ))}
                    </div>
                )}
            </Row>

            <Row label="Secrets" icon={<KeyIcon className="h-3 w-3" />} highlighted={highlightedSection === 'secrets'}>
                {secrets.length === 0 ? (
                    <Empty label="None required" />
                ) : (
                    <div className="flex flex-wrap gap-1.5">
                        {secrets.map((s) => (
                            <Chip key={s} kind="muted">
                                {s}
                            </Chip>
                        ))}
                    </div>
                )}
            </Row>

            <Row label="Limits" icon={<TimerIcon className="h-3 w-3" />} highlighted={highlightedSection === 'limits'}>
                {Object.keys(limits).length === 0 ? (
                    <Empty />
                ) : (
                    <div className="flex flex-wrap gap-3 text-xs">
                        {limits.max_turns !== undefined ? (
                            <LimitStat label="turns" value={String(limits.max_turns)} />
                        ) : null}
                        {limits.max_tool_calls !== undefined ? (
                            <LimitStat label="tool calls" value={String(limits.max_tool_calls)} />
                        ) : null}
                        {limits.max_wall_seconds !== undefined ? (
                            <LimitStat label="wall time" value={`${limits.max_wall_seconds}s`} />
                        ) : null}
                    </div>
                )}
            </Row>

            {auth?.mode ? (
                <Row label="Auth" icon={<ShieldIcon className="h-3 w-3" />}>
                    <Chip kind="muted">mode: {String(auth.mode)}</Chip>
                </Row>
            ) : null}

            {reasoning ? (
                <Row label="Reasoning" icon={<SparklesIcon className="h-3 w-3" />}>
                    <Chip kind="muted">{reasoning}</Chip>
                </Row>
            ) : null}

            {entrypoint && entrypoint !== 'agent.md' ? (
                <Row label="Entrypoint" icon={<CodeIcon className="h-3 w-3" />}>
                    <Chip kind="muted">{entrypoint}</Chip>
                </Row>
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

/* ── Subcomponents ───────────────────────────────────────────────── */

function Row({
    label,
    icon,
    children,
    highlighted,
}: {
    label: string
    icon: ReactNode
    children: ReactNode
    highlighted?: boolean
}): React.ReactElement {
    return (
        <div
            className={
                'rounded-md border bg-card' + (highlighted ? ' border-info ring-1 ring-info/30' : ' border-border')
            }
        >
            <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-3 px-3 py-2.5">
                <div className="flex items-center gap-1.5 text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                    {icon}
                    <span>{label}</span>
                </div>
                <div className="min-w-0">{children}</div>
            </div>
        </div>
    )
}

function Chip({ children, kind = 'default' }: { children: ReactNode; kind?: 'default' | 'muted' }): React.ReactElement {
    const className =
        kind === 'muted'
            ? 'inline-flex items-center gap-1 rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 font-mono text-[0.6875rem] text-muted-foreground'
            : 'inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 font-mono text-[0.6875rem] text-foreground'
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

/* ── Tools / MCPs / Skills ───────────────────────────────────────── */

function ToolRow({
    tool,
    onNativeClick,
    onClientClick,
    onCustomClick,
}: {
    tool: ToolRef
    onNativeClick: (ref: NativeToolRef) => void
    onClientClick: (ref: ClientToolRef) => void
    onCustomClick: (path: string) => void
}): React.ReactElement {
    const clickable = tool.kind === 'native' || tool.kind === 'client' || tool.kind === 'custom'
    const onClick = (): void => {
        if (tool.kind === 'native') {
            onNativeClick(tool)
        } else if (tool.kind === 'client') {
            onClientClick(tool)
        } else if (tool.kind === 'custom') {
            onCustomClick(tool.path)
        }
    }
    return (
        <RefRow
            onClick={clickable ? onClick : undefined}
            kind={tool.kind}
            primary={<code className="font-mono text-[0.6875rem]">{tool.id}</code>}
            secondary={
                tool.kind === 'custom'
                    ? `bundle: ${tool.path}`
                    : tool.kind === 'custom_template'
                      ? `from template ${tool.from_template}`
                      : tool.kind === 'client'
                        ? (tool.description ?? 'client-fulfilled')
                        : undefined
            }
        />
    )
}

function McpRow({ mcp }: { mcp: McpRef }): React.ReactElement {
    if (mcp.kind === 'agent') {
        return (
            <RefRow
                kind="agent"
                primary={<code className="font-mono text-[0.6875rem]">{mcp.slug}</code>}
                secondary="in-platform agent MCP"
            />
        )
    }
    return (
        <RefRow
            kind="external"
            primary={<code className="truncate font-mono text-[0.6875rem]">{mcp.url}</code>}
            secondary={mcp.auth?.integration ? `via integration ${mcp.auth.integration}` : 'no auth'}
        />
    )
}

function SkillRow({ skill, onClick }: { skill: SkillRef; onClick?: (path: string) => void }): React.ReactElement {
    return (
        <RefRow
            onClick={onClick ? () => onClick(skill.path) : undefined}
            kind="skill"
            primary={<code className="font-mono text-[0.6875rem]">{skill.id}</code>}
            secondary={skill.description ?? skill.path}
        />
    )
}

/**
 * Generic clickable row used by Tool / MCP / Skill lists. The `kind` chip
 * gives a quick visual disambiguation between e.g. native and custom tools.
 */
function RefRow({
    kind,
    primary,
    secondary,
    onClick,
}: {
    kind: string
    primary: ReactNode
    secondary?: ReactNode
    onClick?: () => void
}): React.ReactElement {
    const inner = (
        <>
            <span className="inline-flex h-4 shrink-0 items-center rounded-full border border-border/60 bg-muted/40 px-1.5 text-[0.625rem] uppercase tracking-wide text-muted-foreground">
                {kind}
            </span>
            <div className="min-w-0 flex-1">
                <div className="truncate">{primary}</div>
                {secondary ? <div className="truncate text-[0.6875rem] text-muted-foreground">{secondary}</div> : null}
            </div>
        </>
    )
    if (onClick) {
        return (
            <button
                type="button"
                onClick={onClick}
                className="flex items-start gap-2 rounded-md border border-border/60 bg-muted/20 px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-accent/60"
            >
                {inner}
            </button>
        )
    }
    return (
        <div className="flex items-start gap-2 rounded-md border border-border/60 bg-muted/20 px-2.5 py-1.5 text-xs">
            {inner}
        </div>
    )
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
                        <span className="rounded-full border border-border/60 bg-muted/40 px-1.5 py-0.5 text-[0.625rem] uppercase tracking-wide text-muted-foreground">
                            {kind}
                        </span>
                        {costHint ? (
                            <span className="rounded-full border border-border/60 bg-muted/40 px-1.5 py-0.5 text-[0.625rem] uppercase tracking-wide text-muted-foreground">
                                {costHint}
                            </span>
                        ) : null}
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
                    <p className="text-[0.6875rem] italic text-muted-foreground">
                        A future Skills / Tools store will host catalog-style browsing and richer examples; today this
                        dialog reads `/agent_native_tools/` directly.
                    </p>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}

/* ── Triggers ────────────────────────────────────────────────────── */

function TriggerRow({ trigger }: { trigger: Trigger }): React.ReactElement {
    const { Icon, summary, detail } = describeTrigger(trigger)
    return (
        <div className="flex items-start gap-2 rounded-md border border-border/60 bg-muted/20 px-2.5 py-1.5">
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
            return { Icon: HashIcon, summary: 'via chat trigger' }
        default:
            return { Icon: GlobeIcon, summary: '' }
    }
}

/**
 * Escape hatch for spec fields we haven't built structured renderers
 * for yet — shows them as a labeled JsonView so we never silently drop
 * data the user might care about.
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
        <div className="rounded-md border border-border bg-card">
            <div className="px-3 py-2 text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                Other spec fields
            </div>
            <div className="px-3 pb-3">
                <JsonView value={extras} expandToLevel={1} />
            </div>
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
