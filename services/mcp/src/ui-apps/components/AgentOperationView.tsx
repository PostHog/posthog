import './agent-operation.css'

import {
    ArrowUpRight,
    Bug,
    ChartLine,
    CircleCheck,
    Database,
    FileText,
    Flag,
    FlaskConical,
    Globe,
    LayoutDashboard,
    MessageCircleQuestionMark,
    MessageSquarePlus,
    NotebookPen,
    Play,
    Search,
    ShieldQuestionMark,
    Sparkles,
    Table2,
} from 'lucide-react'
import { type ReactElement, type ReactNode, useEffect, useRef, useState } from 'react'

import {
    Button,
    Card,
    ChatMarker,
    ChatMarkerContent,
    ChatMarkerIcon,
    ChatTask,
    ChatTaskList,
    ChatTaskListContent,
    ChatTaskListCount,
    ChatTaskListLabel,
    ChatTaskListProgress,
    ChatTaskListTrigger,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Dot,
    Field,
    Heading,
    Highlight,
    Spinner,
    Text,
    Textarea,
} from '@posthog/quill'

import {
    type AgentOperation,
    type AgentOperationApproval,
    type AgentOperationPlanItem,
    type AgentOperationState,
    APPROVAL_REPLIES,
} from '../../tools/posthogAgent/operations'
import { Markdown } from '../lib/Markdown'
import { PostHogLogo } from './PostHogLogo'

type Phase = 'starting' | 'working' | 'approval' | 'question' | 'stopping' | 'done' | 'failed' | 'canceled' | 'expired'

const TERMINAL_STATES: ReadonlySet<AgentOperationState> = new Set(['succeeded', 'failed', 'cancelled', 'expired'])
const VISIBLE_STEPS = 6
const MAX_KEPT_STEPS = 200
const CONFETTI_PIECES = 16
const CONFETTI_MS = 1800

const PHASE_LABELS: Record<Phase, string> = {
    starting: 'Starting',
    working: 'Working',
    approval: 'Waiting for your approval',
    question: 'Waiting for your answer',
    stopping: 'Stopping',
    done: 'Done',
    failed: 'Failed',
    canceled: 'Canceled',
    expired: 'Timed out',
}

const PHASE_DOTS: Record<Phase, 'default' | 'info' | 'warning' | 'success' | 'destructive'> = {
    starting: 'info',
    working: 'info',
    approval: 'warning',
    question: 'warning',
    stopping: 'warning',
    done: 'success',
    failed: 'destructive',
    canceled: 'default',
    expired: 'destructive',
}

const REASON_LABELS: Record<string, string> = {
    deadline: 'The run stopped at its 2-hour limit.',
    no_result: 'PostHog AI ended without a result. Open the conversation in PostHog to see what happened.',
    credential_revoked: 'The key that started this run was revoked.',
    run_failed: 'The run failed. Open the conversation in PostHog to see what happened.',
    run_missing: 'The run no longer exists.',
    run_cancelled: 'Someone stopped the run in PostHog.',
    agent_reported_failure: 'PostHog AI could not complete the request.',
    dispatch_failed: 'The run could not start. Try again in a moment.',
}

const ANSWERED_LABELS: Record<string, string> = {
    [APPROVAL_REPLIES.allow]: 'You allowed this step. PostHog AI is continuing.',
    [APPROVAL_REPLIES.allowAll]: 'You allowed steps like this for the rest of the run.',
    [APPROVAL_REPLIES.deny]: 'You denied this step. PostHog AI will try another way.',
}

const STEP_ICONS: Array<[RegExp, ReactElement]> = [
    [/sql|query|hogql/i, <Database key="sql" />],
    [/dashboard/i, <LayoutDashboard key="dashboard" />],
    [/insight|trend|funnel|retention|chart/i, <ChartLine key="insight" />],
    [/schema|propert|event|table|column/i, <Table2 key="schema" />],
    [/flag/i, <Flag key="flag" />],
    [/experiment/i, <FlaskConical key="experiment" />],
    [/error|exception|issue/i, <Bug key="error" />],
    [/replay|recording|session/i, <Play key="replay" />],
    [/notebook/i, <NotebookPen key="notebook" />],
    [/web|search the|fetch/i, <Globe key="web" />],
    [/search|find|look/i, <Search key="search" />],
    [/file|code|read/i, <FileText key="file" />],
]

export function isTerminal(operation: AgentOperation): boolean {
    return TERMINAL_STATES.has(operation.state)
}

function phaseOf(operation: AgentOperation): Phase {
    switch (operation.state) {
        case 'queued':
            return 'starting'
        case 'running':
            return 'working'
        case 'needs_input':
            return operation.approval ? 'approval' : 'question'
        case 'cancelling':
            return 'stopping'
        case 'succeeded':
            return 'done'
        case 'failed':
            return 'failed'
        case 'cancelled':
            return 'canceled'
        case 'expired':
            return 'expired'
    }
}

function isWorking(phase: Phase): boolean {
    return phase === 'starting' || phase === 'working' || phase === 'stopping'
}

function stepIcon(label: string): ReactElement {
    return STEP_ICONS.find(([pattern]) => pattern.test(label))?.[1] ?? <Sparkles />
}

/**
 * The approval detail is the PostHog command, such as `call execute-sql {"query": "..."}`. Show the SQL
 * itself, or the input as indented JSON, because that is what the user decides on.
 */
function readableDetail(detail: string): string {
    const match = /^call\s+[\w-]+\s+(\{[\s\S]*\})$/.exec(detail.trim())
    if (!match?.[1]) {
        return detail
    }
    try {
        const input = JSON.parse(match[1]) as Record<string, unknown>
        return typeof input.query === 'string' ? input.query : JSON.stringify(input, null, 2)
    } catch {
        return detail
    }
}

/** The first sentence of the request, so a long prompt written by the calling agent does not fill the card. */
function requestTitle(goal: string): string {
    const firstLine = goal.trim().split('\n')[0] ?? ''
    const sentence = /^(.+?[.?!])(\s|$)/.exec(firstLine)?.[1] ?? firstLine
    return sentence.length > 140 ? `${sentence.slice(0, 137).trimEnd()}…` : sentence
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
    const ticking = !isTerminal(operation)
    useEffect(() => {
        if (!ticking) {
            return
        }
        const timer = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(timer)
    }, [ticking])
    const start = Date.parse(operation.created_at)
    const end = operation.finished_at ? Date.parse(operation.finished_at) : now
    return Number.isNaN(start) ? '' : formatElapsed(end - start)
}

/** Keeps the steps of every response, because each response only carries the steps after its cursor. */
function useStepFeed(operation: AgentOperation): string[] {
    const [feed, setFeed] = useState<{ cursors: Set<string>; steps: string[] }>(() => ({
        cursors: new Set([operation.cursor]),
        steps: operation.new_steps,
    }))
    useEffect(() => {
        setFeed((prev) => {
            if (prev.cursors.has(operation.cursor) || operation.new_steps.length === 0) {
                return prev
            }
            const cursors = new Set(prev.cursors).add(operation.cursor)
            return { cursors, steps: [...prev.steps, ...operation.new_steps].slice(-MAX_KEPT_STEPS) }
        })
    }, [operation.cursor, operation.new_steps])
    return feed.steps
}

/** Plays the confetti once, when this view sees the run finish. A view that opens on a finished run stays calm. */
function useCelebration(operation: AgentOperation): boolean {
    const previous = useRef(operation.state)
    const [celebrating, setCelebrating] = useState(false)
    useEffect(() => {
        const finishedNow = operation.state === 'succeeded' && !TERMINAL_STATES.has(previous.current)
        previous.current = operation.state
        if (!finishedNow) {
            return
        }
        setCelebrating(true)
        const timer = setTimeout(() => setCelebrating(false), CONFETTI_MS)
        return () => clearTimeout(timer)
    }, [operation.state])
    return celebrating
}

function Confetti(): ReactElement {
    return (
        <div className="agent-confetti" aria-hidden>
            {Array.from({ length: CONFETTI_PIECES }, (_, index) => (
                <span key={index} className="agent-confetti__piece" />
            ))}
        </div>
    )
}

function AgentMark({ active }: { active: boolean }): ReactElement {
    return (
        <span
            className={`flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background ${active ? 'agent-mark--active' : ''}`}
            aria-hidden
        >
            <PostHogLogo size={20} />
        </span>
    )
}

function StatusLine({ phase, elapsed }: { phase: Phase; elapsed: string }): ReactElement {
    return (
        <span className="flex min-w-0 items-center gap-2">
            {isWorking(phase) ? (
                <Spinner className="size-3.5 text-info-foreground" />
            ) : (
                <Dot variant={PHASE_DOTS[phase]} pulse={phase === 'approval' || phase === 'question'} />
            )}
            <Text size="sm" weight="medium" render={<span />}>
                {phase === 'done' ? (
                    <Highlight color="green" animate>
                        {PHASE_LABELS[phase]}
                    </Highlight>
                ) : (
                    PHASE_LABELS[phase]
                )}
            </Text>
            {elapsed && (
                <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                    {elapsed}
                </Text>
            )}
        </span>
    )
}

function Header({
    operation,
    phase,
    elapsed,
    action,
}: {
    operation: AgentOperation
    phase: Phase
    elapsed: string
    action?: ReactNode
}): ReactElement {
    return (
        <div className="flex items-center gap-3">
            <AgentMark active={isWorking(phase)} />
            <div className="flex min-w-0 flex-1 flex-col">
                <Text size="xs" variant="muted" className="truncate">
                    PostHog Agent · {operation.project.name}
                </Text>
                <StatusLine phase={phase} elapsed={elapsed} />
            </div>
            {action}
        </div>
    )
}

function RequestTitle({ goal }: { goal: string }): ReactElement {
    const title = requestTitle(goal)
    const hasMore = goal.trim() !== title
    return (
        <div className="flex flex-col gap-1">
            <Heading size="base" render={<h2 />} className="line-clamp-2 break-words">
                {title}
            </Heading>
            {hasMore && (
                <Collapsible>
                    <CollapsibleTrigger render={<Button variant="link-muted" size="xs" className="px-0" />}>
                        Show full request
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                        <Text size="xs" variant="muted" className="mt-1 whitespace-pre-wrap break-words">
                            {goal}
                        </Text>
                    </CollapsibleContent>
                </Collapsible>
            )}
        </div>
    )
}

const CHAT_HINT = 'Answer in the chat to continue.'

function ApprovalCard({
    approval,
    canReply,
    onReply,
    pendingReply,
}: {
    approval: AgentOperationApproval
    canReply: boolean
    onReply: (message: string) => void
    pendingReply: string | null
}): ReactElement {
    const busy = pendingReply !== null
    const buttons = [
        { message: APPROVAL_REPLIES.allow, label: 'Allow', variant: 'primary' },
        { message: APPROVAL_REPLIES.allowAll, label: 'Allow for this run', variant: 'outline' },
        { message: APPROVAL_REPLIES.deny, label: 'Deny', variant: 'destructive-outline' },
    ] as const
    return (
        <section
            aria-label="Approval needed"
            className="agent-attention flex flex-col gap-3 rounded-lg border border-warning-foreground/30 bg-warning p-3"
        >
            <div className="flex items-start gap-2">
                <ShieldQuestionMark className="mt-0.5 size-4 shrink-0 text-warning-foreground" />
                <div className="flex min-w-0 flex-col gap-0.5">
                    <Text size="sm" weight="semibold">
                        Allow PostHog AI to run this step?
                    </Text>
                    <Text size="sm" className="break-words">
                        {approval.title}
                    </Text>
                </div>
            </div>
            {approval.detail && (
                <pre className="max-h-40 overflow-auto rounded-md border bg-background p-2 font-mono text-xs whitespace-pre-wrap break-words">
                    {readableDetail(approval.detail)}
                </pre>
            )}
            {canReply ? (
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap gap-2">
                        {buttons.map((button) => (
                            <Button
                                key={button.message}
                                variant={button.variant}
                                size="sm"
                                loading={pendingReply === button.message}
                                disabled={busy}
                                onClick={() => onReply(button.message)}
                            >
                                {button.label}
                            </Button>
                        ))}
                    </div>
                    <Text size="xs" variant="muted">
                        Allow for this run lets PostHog AI run steps like this until the run ends.
                    </Text>
                </div>
            ) : (
                <Text size="xs" variant="muted">
                    {CHAT_HINT}
                </Text>
            )}
        </section>
    )
}

function QuestionCard({
    question,
    canReply,
    onReply,
    pendingReply,
    onOpenLink,
}: {
    question: string
    canReply: boolean
    onReply: (message: string) => void
    pendingReply: string | null
    onOpenLink: (url: string) => void
}): ReactElement {
    const [answer, setAnswer] = useState('')
    const busy = pendingReply !== null
    const trimmed = answer.trim()
    return (
        <section
            aria-label="Question from PostHog AI"
            className="agent-attention flex flex-col gap-3 rounded-lg border border-warning-foreground/30 bg-warning p-3"
        >
            <div className="flex items-start gap-2">
                <MessageCircleQuestionMark className="mt-0.5 size-4 shrink-0 text-warning-foreground" />
                <div className="flex min-w-0 flex-col gap-1">
                    <Text size="sm" weight="semibold">
                        PostHog AI has a question
                    </Text>
                    <Markdown source={question} onOpenLink={onOpenLink} />
                </div>
            </div>
            {canReply ? (
                <form
                    className="flex flex-col gap-2"
                    onSubmit={(e) => {
                        e.preventDefault()
                        if (trimmed && !busy) {
                            onReply(trimmed)
                        }
                    }}
                >
                    <Field>
                        <Textarea
                            aria-label="Your answer"
                            placeholder="Type your answer"
                            rows={3}
                            value={answer}
                            disabled={busy}
                            className="bg-background"
                            onChange={(e) => setAnswer(e.target.value)}
                        />
                    </Field>
                    <div>
                        <Button type="submit" variant="primary" size="sm" loading={busy} disabled={!trimmed}>
                            Send answer
                        </Button>
                    </div>
                </form>
            ) : (
                <Text size="xs" variant="muted">
                    {CHAT_HINT}
                </Text>
            )}
        </section>
    )
}

function planTaskStatus(item: AgentOperationPlanItem, live: boolean): 'pending' | 'active' | 'done' {
    if (item.status === 'completed') {
        return 'done'
    }
    return item.status === 'in_progress' && live ? 'active' : 'pending'
}

function PlanList({
    plan,
    live,
    defaultOpen,
}: {
    plan: AgentOperationPlanItem[]
    live: boolean
    defaultOpen: boolean
}): ReactElement {
    const done = plan.filter((item) => item.status === 'completed').length
    return (
        <ChatTaskList value={done} total={plan.length} defaultOpen={defaultOpen}>
            <ChatTaskListTrigger>
                <ChatTaskListProgress />
                <ChatTaskListLabel>Plan</ChatTaskListLabel>
                <ChatTaskListCount />
            </ChatTaskListTrigger>
            <ChatTaskListContent>
                {plan.map((item, index) => (
                    <ChatTask key={index} status={planTaskStatus(item, live)}>
                        {item.content}
                    </ChatTask>
                ))}
            </ChatTaskListContent>
        </ChatTaskList>
    )
}

/** Without a plan, the steps themselves are the checklist: each finished step is checked off. */
function StepList({ steps, total, working }: { steps: string[]; total: number; working: boolean }): ReactElement {
    const shown = steps.slice(-VISIBLE_STEPS)
    const earlier = Math.max(0, total - shown.length)
    const done = working ? Math.max(0, total - 1) : total
    return (
        <ChatTaskList value={done} total={total} defaultOpen>
            <ChatTaskListTrigger>
                <ChatTaskListLabel>Steps</ChatTaskListLabel>
                <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                    {working ? `${done} done` : `${total} done`}
                </Text>
            </ChatTaskListTrigger>
            <ChatTaskListContent>
                {earlier > 0 && (
                    <ChatTask status="done">
                        <Text size="xs" variant="muted" render={<span />}>
                            {earlier === 1 ? '1 earlier step' : `${earlier} earlier steps`}
                        </Text>
                    </ChatTask>
                )}
                {shown.map((step, index) => (
                    <ChatTask
                        key={earlier + index}
                        status={working && index === shown.length - 1 ? 'active' : 'done'}
                        truncate
                    >
                        {step}
                    </ChatTask>
                ))}
            </ChatTaskListContent>
        </ChatTaskList>
    )
}

/** With a plan, the plan is the checklist and the steps behind it fold into one activity row. */
function ActivityLog({ steps, total, working }: { steps: string[]; total: number; working: boolean }): ReactElement {
    const latest = steps[steps.length - 1]
    return (
        <ChatMarker
            status={working ? 'running' : 'done'}
            body={
                <>
                    {steps.slice(-VISIBLE_STEPS * 2).map((step, index) => (
                        <ChatMarker key={index} status="done">
                            <ChatMarkerIcon>{stepIcon(step)}</ChatMarkerIcon>
                            <ChatMarkerContent>{step}</ChatMarkerContent>
                        </ChatMarker>
                    ))}
                </>
            }
        >
            <ChatMarkerContent>
                {working && latest ? `${latest} · ${total} steps so far` : `Ran ${total} steps`}
            </ChatMarkerContent>
        </ChatMarker>
    )
}

function CurrentStep({ label }: { label: string }): ReactElement {
    return (
        <ChatMarker status="running">
            <ChatMarkerIcon>{stepIcon(label)}</ChatMarkerIcon>
            <ChatMarkerContent>{label}</ChatMarkerContent>
        </ChatMarker>
    )
}

function LinkRow({
    label,
    meta,
    url,
    onOpenLink,
}: {
    label: string
    meta?: string
    url: string | null
    onOpenLink: (url: string) => void
}): ReactElement {
    const content = (
        <>
            <span className="min-w-0 truncate">{label}</span>
            {meta && (
                <Text size="xs" variant="muted" render={<span />} className="shrink-0">
                    {meta}
                </Text>
            )}
            {url && <ArrowUpRight className="ms-auto size-3.5 shrink-0 text-muted-foreground" />}
        </>
    )
    if (!url) {
        return <li className="flex items-center gap-2 px-2 py-1.5 text-sm">{content}</li>
    }
    return (
        <li>
            <a
                href={url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => {
                    e.preventDefault()
                    onOpenLink(url)
                }}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-fill-hover"
            >
                {content}
            </a>
        </li>
    )
}

function SectionLabel({ children }: { children: ReactNode }): ReactElement {
    return (
        <Text size="xs" weight="medium" variant="muted">
            {children}
        </Text>
    )
}

function ResultSection({
    result,
    onOpenLink,
    onAskFollowUp,
}: {
    result: NonNullable<AgentOperation['result']>
    onOpenLink: (url: string) => void
    onAskFollowUp?: (text: string) => void
}): ReactElement {
    const links = [
        ...result.artifacts.map((item) => ({ label: item.name, meta: item.type, url: item.url })),
        ...result.evidence.map((item) => ({ label: item.label, meta: undefined, url: item.url })),
    ]
    return (
        <div className="flex flex-col gap-4">
            {result.answer && <Markdown source={result.answer} onOpenLink={onOpenLink} />}
            {result.assumptions.length > 0 && (
                <Collapsible>
                    <CollapsibleTrigger render={<Button variant="link-muted" size="xs" className="px-0" />}>
                        {result.assumptions.length === 1 ? '1 assumption' : `${result.assumptions.length} assumptions`}
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                        <ul className="mt-1 flex list-disc flex-col gap-1 ps-5 text-sm">
                            {result.assumptions.map((item, index) => (
                                <li key={index}>{item}</li>
                            ))}
                        </ul>
                    </CollapsibleContent>
                </Collapsible>
            )}
            {links.length > 0 && (
                <div className="flex flex-col gap-1">
                    <SectionLabel>Sources and changes</SectionLabel>
                    <ul className="-mx-2 flex flex-col">
                        {links.map((link, index) => (
                            <LinkRow key={index} {...link} onOpenLink={onOpenLink} />
                        ))}
                    </ul>
                </div>
            )}
            {result.follow_ups.length > 0 && (
                <div className="flex flex-col gap-2">
                    <SectionLabel>Ask next</SectionLabel>
                    {onAskFollowUp ? (
                        <div className="flex flex-wrap gap-2">
                            {result.follow_ups.map((item, index) => (
                                <Button
                                    key={index}
                                    variant="outline"
                                    size="sm"
                                    className="h-auto max-w-full py-1 text-left whitespace-normal"
                                    onClick={() => onAskFollowUp(item)}
                                >
                                    <MessageSquarePlus />
                                    {item}
                                </Button>
                            ))}
                        </div>
                    ) : (
                        <ul className="flex list-disc flex-col gap-1 ps-5 text-sm">
                            {result.follow_ups.map((item, index) => (
                                <li key={index}>{item}</li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    )
}

function Footer({
    operation,
    onOpenLink,
}: {
    operation: AgentOperation
    onOpenLink: (url: string) => void
}): ReactElement {
    return (
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            {operation.repository && (
                <Text size="xs" variant="muted" render={<span />} className="break-all">
                    {operation.repository}
                    {operation.resolved_commit ? `@${operation.resolved_commit.slice(0, 7)}` : ''}
                </Text>
            )}
            <Button variant="default" size="sm" className="ms-auto" onClick={() => onOpenLink(operation.posthog_url)}>
                Open in PostHog
                <ArrowUpRight />
            </Button>
        </div>
    )
}

export interface AgentOperationViewProps {
    operation: AgentOperation
    onOpenLink: (url: string) => void
    canControl: boolean
    pollError: string | null
    onCancel: () => void
    cancelling: boolean
    cancelError: string | null
    onReply: (message: string) => void
    pendingReply: string | null
    replyError: string | null
    /** The last reply sent from this view, shown as a confirmation once the run moves on. */
    answered?: string | null
    /** The approval that this view answered. It stays hidden while the run log catches up. */
    answeredApprovalId?: string | null
    onAskFollowUp?: (text: string) => void
}

export function AgentOperationView({
    operation: received,
    onOpenLink,
    canControl,
    pollError,
    onCancel,
    cancelling,
    cancelError,
    onReply,
    pendingReply,
    replyError,
    answered,
    answeredApprovalId,
    onAskFollowUp,
}: AgentOperationViewProps): ReactElement {
    const operation: AgentOperation =
        received.approval && received.approval.request_id === answeredApprovalId
            ? { ...received, state: 'running', state_reason: null, approval: null }
            : received
    const phase = phaseOf(operation)
    const working = isWorking(phase)
    const terminal = isTerminal(operation)
    const elapsed = useElapsed(operation)
    const steps = useStepFeed(operation)
    const celebrating = useCelebration(operation)
    const stepsTotal = Math.max(operation.steps_total, steps.length)
    const question = operation.result?.question ?? operation.question
    const canReply = canControl && operation.state === 'needs_input'
    const canCancel = canControl && !terminal && operation.state !== 'cancelling'
    const reason = operation.state_reason ? REASON_LABELS[operation.state_reason] : undefined
    const error = cancelError ?? replyError ?? pollError

    return (
        <Card className="relative m-2 flex flex-col gap-4 overflow-hidden p-4">
            {celebrating && <Confetti />}
            <Header
                operation={operation}
                phase={phase}
                elapsed={elapsed}
                action={
                    canCancel ? (
                        <Button variant="default" size="sm" loading={cancelling} onClick={onCancel}>
                            Cancel
                        </Button>
                    ) : undefined
                }
            />
            <RequestTitle goal={operation.goal} />

            {operation.approval ? (
                <ApprovalCard
                    approval={operation.approval}
                    canReply={canReply}
                    onReply={onReply}
                    pendingReply={pendingReply}
                />
            ) : (
                operation.state === 'needs_input' &&
                question && (
                    <QuestionCard
                        key={question}
                        question={question}
                        canReply={canReply}
                        onReply={onReply}
                        pendingReply={pendingReply}
                        onOpenLink={onOpenLink}
                    />
                )
            )}

            {answered && operation.state !== 'needs_input' && !terminal && (
                <div className="agent-attention flex items-center gap-2">
                    <CircleCheck className="size-4 shrink-0 text-success-foreground" />
                    <Text size="sm">
                        {ANSWERED_LABELS[answered] ?? 'PostHog AI got your answer and is continuing.'}
                    </Text>
                </div>
            )}

            {reason && (
                <div
                    className={`flex flex-col gap-0.5 rounded-lg border p-3 ${phase === 'canceled' ? '' : 'border-destructive-foreground/30 bg-destructive'}`}
                >
                    <Text size="sm" weight="semibold">
                        {PHASE_LABELS[phase]}
                    </Text>
                    <Text size="sm" variant={phase === 'canceled' ? 'muted' : 'default'}>
                        {reason}
                        {operation.result?.answer ? ' What it found is below.' : ''}
                    </Text>
                </div>
            )}

            {operation.plan.length > 0 && (
                <PlanList plan={operation.plan} live={!terminal} defaultOpen={!operation.result} />
            )}
            {steps.length > 0 &&
                (operation.plan.length > 0 || operation.result ? (
                    <ActivityLog steps={steps} total={stepsTotal} working={working} />
                ) : (
                    <StepList steps={steps} total={stepsTotal} working={working} />
                ))}
            {working && steps.length === 0 && operation.plan.length === 0 && (
                <CurrentStep label={phase === 'starting' ? 'Starting a sandbox for PostHog AI' : 'Getting started'} />
            )}

            {!operation.result && operation.summary && working && (
                <Text size="sm" variant="muted" className="whitespace-pre-wrap break-words">
                    {operation.summary}
                </Text>
            )}

            {operation.result && operation.state !== 'needs_input' && (
                <ResultSection result={operation.result} onOpenLink={onOpenLink} onAskFollowUp={onAskFollowUp} />
            )}

            {error && (
                <Text size="xs" variant="destructive">
                    {error}
                </Text>
            )}

            <Footer operation={operation} onOpenLink={onOpenLink} />
        </Card>
    )
}
