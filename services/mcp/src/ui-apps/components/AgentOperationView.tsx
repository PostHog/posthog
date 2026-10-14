import { CheckCircle2, Circle, CircleDot, ExternalLink } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Separator, Spinner } from '@posthog/quill'

import type { AgentOperation, AgentOperationState } from '../../tools/posthogAgent/operations'

const TERMINAL_STATES: ReadonlySet<AgentOperationState> = new Set(['succeeded', 'failed', 'cancelled', 'expired'])
const ACTIVITY_LIMIT = 8

const STATE_LABELS: Record<AgentOperationState, string> = {
    queued: 'Queued',
    running: 'Running',
    needs_input: 'Needs input',
    cancelling: 'Cancelling',
    succeeded: 'Succeeded',
    failed: 'Failed',
    cancelled: 'Cancelled',
    expired: 'Expired',
}

const REASON_LABELS: Record<string, string> = {
    deadline: 'Stopped at the 2-hour limit.',
    no_result: 'PostHog AI ended without a result.',
    credential_revoked: 'The key that started this operation was revoked.',
    run_failed: 'The run failed.',
    run_missing: 'The run no longer exists.',
    run_cancelled: 'The run was stopped in PostHog.',
    agent_reported_failure: 'PostHog AI could not complete the goal.',
    dispatch_failed: 'The task could not start.',
}

type BadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success'

const STATE_VARIANTS: Record<AgentOperationState, BadgeVariant> = {
    queued: 'default',
    running: 'info',
    needs_input: 'warning',
    cancelling: 'warning',
    succeeded: 'success',
    failed: 'destructive',
    cancelled: 'default',
    expired: 'destructive',
}

export function isTerminal(operation: AgentOperation): boolean {
    return TERMINAL_STATES.has(operation.state)
}

function formatElapsed(ms: number): string {
    const totalSeconds = Math.max(0, Math.floor(ms / 1000))
    const hours = Math.floor(totalSeconds / 3600)
    const minutes = Math.floor((totalSeconds % 3600) / 60)
    const seconds = totalSeconds % 60
    if (hours > 0) {
        return `${hours}h ${minutes}m`
    }
    return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`
}

function useElapsed(operation: AgentOperation): string {
    const [now, setNow] = useState(() => Date.now())
    const running = !isTerminal(operation)
    useEffect(() => {
        if (!running) {
            return
        }
        const timer = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(timer)
    }, [running])
    const start = Date.parse(operation.created_at)
    const end = operation.finished_at ? Date.parse(operation.finished_at) : now
    return Number.isNaN(start) ? '' : formatElapsed(end - start)
}

/** Keeps the steps of every response, because each response only carries the steps since the last cursor. */
function useActivityFeed(operation: AgentOperation): string[] {
    const [feed, setFeed] = useState<{ cursors: Set<string>; steps: string[] }>({ cursors: new Set(), steps: [] })
    useEffect(() => {
        setFeed((prev) => {
            if (prev.cursors.has(operation.cursor) || operation.new_steps.length === 0) {
                return prev
            }
            const cursors = new Set(prev.cursors).add(operation.cursor)
            return { cursors, steps: [...prev.steps, ...operation.new_steps].slice(-ACTIVITY_LIMIT) }
        })
    }, [operation.cursor, operation.new_steps])
    return feed.steps
}

function LinkText({
    label,
    url,
    onOpenLink,
}: {
    label: string
    url: string | null
    onOpenLink: (url: string) => void
}): JSX.Element {
    if (!url) {
        return <span>{label}</span>
    }
    return (
        <a
            href={url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => {
                e.preventDefault()
                onOpenLink(url)
            }}
            className="inline-flex items-center gap-1 text-link underline underline-offset-2"
        >
            {label}
            <ExternalLink className="size-3" />
        </a>
    )
}

function Section({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-1.5">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
            {children}
        </section>
    )
}

function PlanChecklist({ plan }: { plan: AgentOperation['plan'] }): JSX.Element {
    return (
        <ul className="flex flex-col gap-1 text-sm">
            {plan.map((item, index) => (
                <li key={index} className="flex items-start gap-2">
                    {item.status === 'completed' ? (
                        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-foreground" />
                    ) : item.status === 'in_progress' ? (
                        <CircleDot className="mt-0.5 size-4 shrink-0 text-info-foreground" />
                    ) : (
                        <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                    )}
                    <span className={item.status === 'completed' ? 'text-muted-foreground' : ''}>{item.content}</span>
                </li>
            ))}
        </ul>
    )
}

function ResultView({
    result,
    onOpenLink,
}: {
    result: NonNullable<AgentOperation['result']>
    onOpenLink: (url: string) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <Section title="Answer">
                <div className="text-sm whitespace-pre-wrap break-words">{result.answer}</div>
            </Section>
            {result.assumptions.length > 0 && (
                <Section title="Assumptions">
                    <ul className="list-disc pl-5 text-sm">
                        {result.assumptions.map((item, index) => (
                            <li key={index}>{item}</li>
                        ))}
                    </ul>
                </Section>
            )}
            {result.evidence.length > 0 && (
                <Section title="Evidence">
                    <ul className="list-disc pl-5 text-sm">
                        {result.evidence.map((item, index) => (
                            <li key={index}>
                                <LinkText label={item.label} url={item.url} onOpenLink={onOpenLink} />
                            </li>
                        ))}
                    </ul>
                </Section>
            )}
            {result.artifacts.length > 0 && (
                <Section title="Artifacts">
                    <ul className="list-disc pl-5 text-sm">
                        {result.artifacts.map((item, index) => (
                            <li key={index}>
                                <span className="text-muted-foreground">{item.type}: </span>
                                <LinkText label={item.name} url={item.url} onOpenLink={onOpenLink} />
                            </li>
                        ))}
                    </ul>
                </Section>
            )}
            {result.follow_ups.length > 0 && (
                <Section title="Possible follow-ups">
                    <ul className="list-disc pl-5 text-sm">
                        {result.follow_ups.map((item, index) => (
                            <li key={index}>{item}</li>
                        ))}
                    </ul>
                </Section>
            )}
        </div>
    )
}

export function AgentOperationView({
    operation,
    onOpenLink,
    canControl,
    pollError,
    onCancel,
    cancelling,
    cancelError,
}: {
    operation: AgentOperation
    onOpenLink: (url: string) => void
    canControl: boolean
    pollError: string | null
    onCancel: () => void
    cancelling: boolean
    cancelError: string | null
}): JSX.Element {
    const elapsed = useElapsed(operation)
    const activity = useActivityFeed(operation)
    const terminal = isTerminal(operation)
    const question = operation.result?.question ?? operation.question
    const canCancel = !terminal && operation.state !== 'cancelling'

    return (
        <Card className="m-3">
            <CardHeader className="flex flex-col gap-2">
                <div className="flex w-full flex-wrap items-center gap-2">
                    <Badge variant={STATE_VARIANTS[operation.state]}>{STATE_LABELS[operation.state]}</Badge>
                    {!terminal && operation.state !== 'needs_input' && <Spinner className="size-3.5" />}
                    {elapsed && <span className="text-xs text-muted-foreground">{elapsed}</span>}
                    {canCancel && (
                        <div className="ml-auto">
                            <Button variant="outline" size="sm" onClick={onCancel} disabled={cancelling || !canControl}>
                                {cancelling ? 'Cancelling…' : 'Cancel'}
                            </Button>
                        </div>
                    )}
                </div>
                <CardTitle className="text-base break-words">{operation.goal}</CardTitle>
                {operation.state_reason && REASON_LABELS[operation.state_reason] && (
                    <p className="text-xs text-muted-foreground">{REASON_LABELS[operation.state_reason]}</p>
                )}
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span>Project: {operation.project.name}</span>
                    {operation.repository && (
                        <span className="break-all">
                            Repository: {operation.repository}
                            {operation.resolved_commit ? `@${operation.resolved_commit.slice(0, 12)}` : ''}
                        </span>
                    )}
                </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
                {question && (
                    <div className="rounded border border-warning bg-warning/10 p-2 text-sm">
                        <p className="font-semibold">PostHog AI needs input</p>
                        <p className="whitespace-pre-wrap break-words">{question}</p>
                        <p className="mt-1 text-xs text-muted-foreground">Answer in the chat to continue.</p>
                    </div>
                )}
                {operation.plan.length > 0 && (
                    <Section title="Plan">
                        <PlanChecklist plan={operation.plan} />
                    </Section>
                )}
                {!operation.result && activity.length > 0 && (
                    <Section title="Activity">
                        <ul className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                            {activity.map((step, index) => (
                                <li key={index} className="break-words">
                                    {step}
                                </li>
                            ))}
                        </ul>
                    </Section>
                )}
                {!operation.result && operation.summary && (
                    <p className="text-sm whitespace-pre-wrap break-words">{operation.summary}</p>
                )}
                {operation.result && (
                    <>
                        <Separator />
                        <ResultView result={operation.result} onOpenLink={onOpenLink} />
                    </>
                )}
                {(pollError || cancelError) && (
                    <p className="text-xs text-destructive-foreground">{cancelError ?? pollError}</p>
                )}
            </CardContent>
        </Card>
    )
}
