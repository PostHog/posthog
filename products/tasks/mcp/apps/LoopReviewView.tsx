import { Check } from 'lucide-react'
import { type ReactElement, type ReactNode } from 'react'

import { DescriptionList } from '@posthog/mcp-ui'
import { Button, Card, CardContent } from '@posthog/quill'

export interface LoopReviewRepository {
    github_integration_id: number
    full_name: string
}

export interface LoopReviewTrigger {
    type: 'schedule' | 'github' | 'api' | string
    enabled?: boolean
    config?: Record<string, unknown>
}

export interface LoopReviewBehaviors {
    create_prs?: boolean
    watch_ci?: boolean
    fix_review_comments?: boolean
    max_fix_iterations?: number
}

export interface LoopReviewContextOutputs {
    post_to_feed?: boolean
    update_context?: boolean
    canvas_id?: string | null
}

export interface LoopReviewContextTarget {
    name?: string
    folder_id?: string
    outputs?: LoopReviewContextOutputs
}

export interface LoopReviewNotificationChannel {
    enabled?: boolean
}

export interface LoopReviewConnectors {
    mcp_installation_ids?: string[]
    posthog_mcp_scopes?: 'read_only' | 'full'
}

/** The loop config the agent assembled — identical in shape to the `loops-create` tool
 * arguments, so the "Create loop" button can forward it unchanged. */
export interface LoopReviewData {
    name?: string
    description?: string
    instructions?: string
    runtime_adapter?: string
    model?: string
    reasoning_effort?: string | null
    visibility?: string
    repositories?: LoopReviewRepository[]
    triggers?: LoopReviewTrigger[]
    enabled?: boolean
    overlap_policy?: 'skip' | 'allow' | 'cancel_previous'
    behaviors?: LoopReviewBehaviors
    connectors?: LoopReviewConnectors
    sandbox_environment?: string | null
    notifications?: Record<string, LoopReviewNotificationChannel>
    context_target?: LoopReviewContextTarget | null
    _posthogUrl?: string
}

export interface LoopReviewState {
    loading: boolean
    error: string | null
    createdName: string | null
}

export interface LoopReviewViewProps {
    data: LoopReviewData
    onCreate?: () => Promise<void>
    state?: LoopReviewState
}

const ADAPTER_LABELS: Record<string, string> = {
    claude: 'Claude Code',
    codex: 'Codex',
}

function stringList(value: unknown): string[] {
    if (typeof value === 'string') {
        return [value]
    }
    if (Array.isArray(value)) {
        return value.filter((item): item is string => typeof item === 'string')
    }
    return []
}

function describeGithubTrigger(config: Record<string, unknown>): string {
    const repository = typeof config.repository === 'string' ? config.repository : 'a repo'
    const filters = (config.filters ?? {}) as Record<string, unknown>
    const actions = [...stringList(filters.actions), ...stringList(filters.action)]
    const events: string[] = []
    for (const raw of stringList(config.events)) {
        // the API also accepts `issues.opened` shorthand; render it as event + action
        const dot = raw.indexOf('.')
        const event = dot > 0 ? raw.slice(0, dot) : raw
        const action = dot > 0 ? raw.slice(dot + 1) : ''
        if (!events.includes(event)) {
            events.push(event)
        }
        if (action && !actions.includes(action)) {
            actions.push(action)
        }
    }
    if (events.length === 0) {
        return `GitHub (${repository})`
    }
    let summary = events.join(', ')
    if (actions.length > 0) {
        summary += ` ${actions.join('/')}`
    }
    const branches = [...stringList(filters.branches), ...stringList(filters.branch)]
    if (branches.length > 0) {
        summary += ` on ${branches.join(', ')}`
    }
    const labels = [...stringList(filters.labels), ...stringList(filters.label)]
    if (labels.length > 0) {
        summary += ` labeled ${labels.join(', ')}`
    }
    return `GitHub (${repository}: ${summary})`
}

function describeTrigger(trigger: LoopReviewTrigger): string {
    if (trigger.type === 'schedule') {
        const config = trigger.config ?? {}
        if (typeof config.run_at === 'string') {
            return 'Once'
        }
        if (typeof config.cron_expression === 'string') {
            return `Schedule (${config.cron_expression})`
        }
        return 'Schedule'
    }
    if (trigger.type === 'github') {
        return describeGithubTrigger(trigger.config ?? {})
    }
    return 'API'
}

const OVERLAP_LABELS: Record<string, string> = {
    skip: 'skips overlapping runs',
    allow: 'allows overlapping runs',
    cancel_previous: 'cancels the previous run',
}

export function describeRunBehavior(data: Pick<LoopReviewData, 'triggers' | 'enabled' | 'overlap_policy'>): string {
    const parts: string[] = []
    if (!data.triggers || data.triggers.length === 0) {
        parts.push('Manual only')
    } else {
        parts.push(data.triggers.map(describeTrigger).join(', '))
    }
    if (data.enabled === false) {
        parts.push('paused')
    }
    // the server defaults overlap_policy to 'skip', so always show the effective policy
    const overlapPolicy = data.overlap_policy ?? 'skip'
    parts.push(OVERLAP_LABELS[overlapPolicy] ?? overlapPolicy)
    return parts.join(' · ')
}

export function describePosthogAccess(connectors: LoopReviewConnectors | undefined): string {
    return connectors?.posthog_mcp_scopes === 'full' ? 'Full (read-write)' : 'Read-only'
}

function describeConnectors(connectors: LoopReviewConnectors | undefined): string {
    const ids = connectors?.mcp_installation_ids ?? []
    return ids.length > 0 ? ids.join(', ') : 'None'
}

function describeRepository(repositories: LoopReviewRepository[] | undefined): string {
    if (!repositories || repositories.length === 0) {
        return 'None (report-only)'
    }
    return repositories.map((repository) => repository.full_name).join(', ')
}

function describeContext(target: LoopReviewContextTarget | null | undefined): string {
    if (!target?.name) {
        return 'Not attached'
    }
    const outputs = target.outputs ?? {}
    const enabled: string[] = []
    if (outputs.post_to_feed) {
        enabled.push('feed')
    }
    if (outputs.update_context) {
        enabled.push('context.md')
    }
    if (outputs.canvas_id) {
        enabled.push('canvas')
    }
    return enabled.length > 0 ? `#${target.name} (${enabled.join(', ')})` : `#${target.name}`
}

function describeNotifications(notifications: Record<string, LoopReviewNotificationChannel> | undefined): string {
    const enabled = Object.entries(notifications ?? {})
        .filter(([, channel]) => channel?.enabled)
        .map(([name]) => name)
    return enabled.length > 0 ? enabled.join(', ') : 'None'
}

function describeModel(data: LoopReviewData): string {
    const adapter = data.runtime_adapter ? (ADAPTER_LABELS[data.runtime_adapter] ?? data.runtime_adapter) : 'Default'
    const model = data.model?.trim() ? data.model : 'Default model'
    const reasoning = data.reasoning_effort ?? 'auto'
    return `${adapter} · ${model} · ${reasoning} reasoning`
}

export function describeFixReviewComments(behaviors: LoopReviewBehaviors | undefined): string {
    if (!behaviors?.fix_review_comments) {
        return 'No'
    }
    const cap = behaviors.max_fix_iterations
    return cap != null ? `Yes (up to ${cap} iterations)` : 'Yes'
}

export function LoopReviewView({ data, onCreate, state }: LoopReviewViewProps): ReactElement {
    const created = state?.createdName

    if (created) {
        return (
            <Card className="m-4">
                <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
                    <div className="flex size-12 items-center justify-center rounded-full bg-success">
                        <Check className="size-7 text-success-foreground" strokeWidth={2.5} />
                    </div>
                    <div className="flex flex-col gap-1">
                        <h2 className="text-lg font-semibold text-foreground">Loop created</h2>
                        <p className="text-base font-medium text-foreground">{created}</p>
                    </div>
                    <p className="text-sm text-muted-foreground">
                        You'll find it on the Loops page. Edit, pause, or run it anytime.
                    </p>
                </CardContent>
            </Card>
        )
    }

    const items: { label: string; value: ReactNode }[] = [
        { label: 'Name', value: data.name?.trim() || 'Not set' },
        ...(data.description?.trim() ? [{ label: 'Description', value: data.description }] : []),
        {
            label: 'Visibility',
            value: data.visibility === 'team' ? 'Team' : 'Personal',
        },
        {
            label: 'What it does',
            value: <span className="whitespace-pre-wrap">{data.instructions?.trim() || 'No prompt'}</span>,
        },
        { label: 'Runs', value: describeRunBehavior(data) },
        { label: 'Context', value: describeContext(data.context_target) },
        { label: 'Repository', value: describeRepository(data.repositories) },
        { label: 'Model', value: describeModel(data) },
        {
            label: 'Opens PRs',
            value: data.behaviors?.create_prs ? 'Yes' : 'No',
        },
        { label: 'Watches CI', value: data.behaviors?.watch_ci ? 'Yes' : 'No' },
        {
            label: 'Fixes review comments',
            value: describeFixReviewComments(data.behaviors),
        },
        {
            label: 'PostHog access',
            value: describePosthogAccess(data.connectors),
        },
        { label: 'Connectors', value: describeConnectors(data.connectors) },
        { label: 'Sandbox', value: data.sandbox_environment || 'None' },
        {
            label: 'Notifications',
            value: describeNotifications(data.notifications),
        },
    ]

    const creating = state?.loading ?? false
    const createDisabled = creating || !onCreate
    const create = (): void => {
        void onCreate?.()
    }

    return (
        <Card className="m-4">
            <CardContent className="flex flex-col gap-4 p-4">
                <div className="flex items-center justify-between gap-4">
                    <div className="flex flex-col gap-0.5">
                        <h2 className="text-base font-semibold text-foreground">Review this loop</h2>
                        <p className="text-sm text-muted-foreground">Check the details below, then create it.</p>
                    </div>
                    <Button
                        className="shrink-0 bg-[#f9bd2b] font-semibold text-black hover:opacity-90"
                        onClick={create}
                        disabled={createDisabled}
                    >
                        {creating ? 'Creating...' : 'Create loop'}
                    </Button>
                </div>

                {state?.error ? (
                    <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-foreground">
                        {state.error}
                    </p>
                ) : null}

                <DescriptionList items={items} />
            </CardContent>
        </Card>
    )
}
