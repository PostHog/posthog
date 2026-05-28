/**
 * `<ConfigPanel />` — structured rendering of an agent revision's spec.
 *
 * The bundle (agent.md + skills + tools) renders as a filesystem
 * elsewhere; this panel covers the "knobs" portion of the spec:
 * model, triggers, secrets, limits, auth.
 *
 * Each row is one config field with a label + value. Triggers render
 * type-aware (cron schedule + tz, slack workspaces, webhook path).
 * Unknown fields fall back to a JsonView so nothing is silently dropped.
 */

import {
    CalendarClockIcon,
    GlobeIcon,
    HashIcon,
    KeyIcon,
    MessageSquareIcon,
    ShieldIcon,
    SparklesIcon,
    TimerIcon,
    WebhookIcon,
    ZapIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'

import { JsonView } from '@posthog/agent-chat'

export interface ConfigPanelProps {
    spec: Record<string, unknown>
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

interface Auth {
    mode?: string
}

export function ConfigPanel({ spec }: ConfigPanelProps): React.ReactElement {
    const model = typeof spec.model === 'string' ? spec.model : undefined
    const triggers = Array.isArray(spec.triggers) ? (spec.triggers as Trigger[]) : []
    const secrets = Array.isArray(spec.secrets) ? (spec.secrets as string[]) : []
    const limits = (spec.limits && typeof spec.limits === 'object' ? spec.limits : {}) as Limits
    const auth = (spec.auth && typeof spec.auth === 'object' ? spec.auth : {}) as Auth

    return (
        <div className="space-y-3">
            <Row label="Model" icon={<SparklesIcon className="h-3 w-3" />}>
                {model ? <Chip>{model}</Chip> : <Empty />}
            </Row>

            <Row label="Triggers" icon={<ZapIcon className="h-3 w-3" />}>
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

            <Row label="Secrets" icon={<KeyIcon className="h-3 w-3" />}>
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

            <Row label="Limits" icon={<TimerIcon className="h-3 w-3" />}>
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
        </div>
    )
}

/* ── Subcomponents ───────────────────────────────────────────────── */

function Row({ label, icon, children }: { label: string; icon: ReactNode; children: ReactNode }): React.ReactElement {
    return (
        <div className="rounded-md border border-border bg-background">
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
            : 'inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-0.5 font-mono text-[0.6875rem] text-foreground'
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
        <div className="rounded-md border border-border bg-background">
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
