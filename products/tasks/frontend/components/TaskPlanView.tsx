import { useMemo } from 'react'

import { IconCheckCircle, IconCircleDashed, IconClock } from '@posthog/icons'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { LogEntry } from '../lib/parse-logs'

type TodoStatus = 'pending' | 'in_progress' | 'completed'

interface TodoItem {
    content: string
    status: TodoStatus
    activeForm?: string
}

interface ExtractedPlan {
    todos: TodoItem[] | null
    todosTimestamp?: string
    planMarkdown: string | null
    planTimestamp?: string
}

function isTodoStatus(value: unknown): value is TodoStatus {
    return value === 'pending' || value === 'in_progress' || value === 'completed'
}

function parseTodos(value: unknown): TodoItem[] | null {
    if (!Array.isArray(value)) {
        return null
    }
    const parsed: TodoItem[] = []
    for (const item of value) {
        if (typeof item !== 'object' || item === null) {
            continue
        }
        const candidate = item as { content?: unknown; status?: unknown; activeForm?: unknown }
        if (typeof candidate.content !== 'string') {
            continue
        }
        parsed.push({
            content: candidate.content,
            status: isTodoStatus(candidate.status) ? candidate.status : 'pending',
            activeForm: typeof candidate.activeForm === 'string' ? candidate.activeForm : undefined,
        })
    }
    return parsed.length > 0 ? parsed : null
}

export function extractCurrentPlan(entries: LogEntry[]): ExtractedPlan {
    let todos: TodoItem[] | null = null
    let todosTimestamp: string | undefined
    let planMarkdown: string | null = null
    let planTimestamp: string | undefined

    for (const entry of entries) {
        if (entry.type !== 'tool' || !entry.toolArgs) {
            continue
        }
        if (entry.toolName === 'TodoWrite') {
            const next = parseTodos((entry.toolArgs as { todos?: unknown }).todos)
            if (next) {
                todos = next
                todosTimestamp = entry.timestamp
            }
        }
        if (entry.toolName === 'ExitPlanMode') {
            const planValue = (entry.toolArgs as { plan?: unknown }).plan
            if (typeof planValue === 'string' && planValue.trim().length > 0) {
                planMarkdown = planValue
                planTimestamp = entry.timestamp
            }
        }
    }

    return { todos, todosTimestamp, planMarkdown, planTimestamp }
}

function TodoStatusIcon({ status }: { status: TodoStatus }): JSX.Element {
    switch (status) {
        case 'completed':
            return <IconCheckCircle className="text-success shrink-0" fontSize="16" />
        case 'in_progress':
            return <IconClock className="text-primary shrink-0" fontSize="16" />
        default:
            return <IconCircleDashed className="text-muted shrink-0" fontSize="16" />
    }
}

function formatTimestamp(timestamp?: string): string | null {
    if (!timestamp) {
        return null
    }
    try {
        return new Date(timestamp).toLocaleTimeString()
    } catch {
        return null
    }
}

export function TaskPlanView({ entries }: { entries: LogEntry[] }): JSX.Element {
    const { todos, todosTimestamp, planMarkdown, planTimestamp } = useMemo(() => extractCurrentPlan(entries), [entries])

    if (!todos?.length && !planMarkdown) {
        return (
            <div className="p-4 text-center text-muted">
                <p>No plan available yet.</p>
                <p className="text-xs mt-1">
                    The agent will populate this view when it shares a plan via TodoWrite or ExitPlanMode.
                </p>
            </div>
        )
    }

    const todosTime = formatTimestamp(todosTimestamp)
    const planTime = formatTimestamp(planTimestamp)

    return (
        <div className="flex flex-col gap-4 font-sans">
            {planMarkdown && (
                <section>
                    <div className="flex items-center gap-2 mb-2">
                        <span className="text-xs font-semibold text-muted uppercase tracking-wide">Proposed plan</span>
                        {planTime && <span className="text-xs text-muted">{planTime}</span>}
                    </div>
                    <div className="rounded border bg-bg-light p-3">
                        <LemonMarkdown lowKeyHeadings className="text-sm">
                            {planMarkdown}
                        </LemonMarkdown>
                    </div>
                </section>
            )}
            {todos?.length ? (
                <section>
                    <div className="flex items-center gap-2 mb-2">
                        <span className="text-xs font-semibold text-muted uppercase tracking-wide">Current todos</span>
                        {todosTime && <span className="text-xs text-muted">{todosTime}</span>}
                    </div>
                    <ul className="flex flex-col gap-1 rounded border bg-bg-light p-3">
                        {todos.map((todo, idx) => (
                            <li key={`${idx}-${todo.content}`} className="flex items-start gap-2 text-sm">
                                <TodoStatusIcon status={todo.status} />
                                <span
                                    className={
                                        todo.status === 'completed'
                                            ? 'text-muted line-through'
                                            : todo.status === 'in_progress'
                                              ? 'font-medium'
                                              : ''
                                    }
                                >
                                    {todo.status === 'in_progress' && todo.activeForm ? todo.activeForm : todo.content}
                                </span>
                            </li>
                        ))}
                    </ul>
                </section>
            ) : null}
        </div>
    )
}
