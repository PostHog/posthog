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
    behaviors?: LoopReviewBehaviors
    notifications?: Record<string, LoopReviewNotificationChannel>
    context_target?: LoopReviewContextTarget | null
    _posthogUrl?: string
    [key: string]: unknown
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
        const repository = (trigger.config?.repository as string | undefined) ?? 'a repo'
        return `GitHub (${repository})`
    }
    return 'API'
}

function describeTriggers(triggers: LoopReviewTrigger[] | undefined): string {
    if (!triggers || triggers.length === 0) {
        return 'Manual only'
    }
    return triggers.map(describeTrigger).join(', ')
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

function describeAutoFix(behaviors: LoopReviewBehaviors | undefined): string {
    return behaviors?.watch_ci && behaviors?.fix_review_comments ? 'On' : 'Off'
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
        { label: 'Visibility', value: data.visibility === 'team' ? 'Team' : 'Personal' },
        {
            label: 'What it does',
            value: <span className="whitespace-pre-wrap">{data.instructions?.trim() || 'No prompt'}</span>,
        },
        { label: 'Runs', value: describeTriggers(data.triggers) },
        { label: 'Context', value: describeContext(data.context_target) },
        { label: 'Repository', value: describeRepository(data.repositories) },
        { label: 'Model', value: describeModel(data) },
        { label: 'Opens PRs', value: data.behaviors?.create_prs ? 'Yes' : 'No' },
        { label: 'Auto-fix PRs', value: describeAutoFix(data.behaviors) },
        { label: 'Notifications', value: describeNotifications(data.notifications) },
    ]

    return (
        <Card className="m-4">
            <CardContent className="flex flex-col gap-4 p-4">
                <div className="flex flex-col gap-1">
                    <h2 className="text-base font-semibold text-foreground">Review this loop</h2>
                    <p className="text-sm text-muted-foreground">Check everything, then create it.</p>
                </div>

                <DescriptionList items={items} />

                {state?.error ? <p className="text-sm text-destructive">{state.error}</p> : null}

                <div className="flex justify-end">
                    <Button
                        onClick={() => {
                            void onCreate?.()
                        }}
                        disabled={state?.loading || !onCreate}
                    >
                        {state?.loading ? 'Creating...' : 'Create loop'}
                    </Button>
                </div>
            </CardContent>
        </Card>
    )
}
