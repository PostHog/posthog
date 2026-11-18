import { Suspense, memo, useState } from 'react'

import {
    IconArrowCircleRight,
    IconCheckCircle,
    IconChevronRight,
    IconCircleDashed,
    IconDocument,
    IconGlobe,
    IconListCheck,
    IconMagicWand,
    IconSearch,
    IconTerminal,
    IconWrench,
} from '@posthog/icons'

// IconRobot is not exported from @posthog/icons — it lives only in the legacy lib icon set.
import { IconRobot } from 'lib/lemon-ui/icons'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { getPlanPayload, PlanCard } from '../PlanCard'
import { EditorSkeleton } from './EditorSkeleton'
import { FilePath } from './FilePath'
import { GenericMcpToolRenderer } from './GenericMcpToolRenderer'
import { getPostHogExecDisplay } from './posthogExecDisplay'
import { ToolActivity } from './ToolActivity'
import {
    MAX_COMMAND_LENGTH,
    MAX_URL_LENGTH,
    formatInput,
    getCommandOutput,
    getContentImage,
    getContentText,
    getFilename,
    getLineCount,
    getReadToolContent,
    getResultCount,
    stripAnsi,
    stripCodeFences,
    truncateText,
} from './toolContentUtils'
import { ToolBody, ToolBodySection, ToolOutput } from './ToolOutput'
import type { ToolRendererProps } from './toolRegistry'

// Monaco-backed read-only file view, lazy so monaco stays out of the always-loaded built-in chunk.
const ReadFileContent = lazyWithRetry(() => import('./ReadFileContent').then((m) => ({ default: m.ReadFileContent })))

function asString(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

function firstLocationPath(props: ToolRendererProps): string | undefined {
    return props.message.locations?.[0]?.path ?? (asString(props.message.rawInput.file_path) || undefined)
}

/** Bash / BashOutput / KillShell — command on the second line, ANSI-stripped output in the body. */
const BashToolRenderer = memo(function BashToolRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const command = asString(message.rawInput.command)
    const description = asString(message.rawInput.description)
    const output = stripAnsi(stripCodeFences(getCommandOutput(message.content, command, message.rawOutput)))

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconTerminal />}
            title={description || message.title || 'Terminal'}
            subtitle={
                command ? (
                    <span className="font-mono" title={command}>
                        {command}
                    </span>
                ) : undefined
            }
            body={output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/** Read / NotebookRead — line/image summary on line 1, file chip on line 2, preview in the body. */
const ReadToolRenderer = memo(function ReadToolRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const path = firstLocationPath(props)
    const image = getContentImage(message.content)
    const text = image ? '' : getReadToolContent(message.content)
    const lineCount = getLineCount(text)

    const title = image
        ? 'Read image'
        : lineCount > 0
          ? `Read ${lineCount} ${lineCount === 1 ? 'line' : 'lines'}`
          : 'Read'

    let body: JSX.Element | undefined
    if (image) {
        body = (
            <img
                src={`data:${image.mimeType};base64,${image.base64}`}
                alt={path ? getFilename(path) : 'Read image'}
                className="max-h-96 max-w-full object-contain rounded bg-surface-secondary p-2"
            />
        )
    } else if (text) {
        body = (
            <Suspense fallback={<EditorSkeleton />}>
                <ReadFileContent text={text} path={path} />
            </Suspense>
        )
    }

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconDocument />}
            title={title}
            subtitle={path ? <FilePath path={path} /> : undefined}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/**
 * ExitPlanMode — `/code`'s `PlanApprovalView`: while the approval is pending the plan renders as the
 * tinted document card directly in the thread (the approval actions live in the composer slot); once
 * resolved it collapses to a status row ("Plan approved…" / "(Plan rejected)") with a show/hide toggle.
 */
const ExitPlanModeRenderer = memo(function ExitPlanModeRenderer(props: ToolRendererProps): JSX.Element | null {
    const { message, turnComplete, turnCancelled } = props
    const [isPlanExpanded, setIsPlanExpanded] = useState(false)
    const { plan: planFromInput } = getPlanPayload(message.rawInput)
    const plan = planFromInput ?? getContentText(message.content)

    const isComplete = message.status === 'completed'
    const isIncomplete = message.status === 'pending' || message.status === 'in_progress'
    // A denied plan surfaces as a failed tool call; a cancelled/finished turn leaves it incomplete forever.
    const wasRejected = message.status === 'failed' || (isIncomplete && !!(turnCancelled || turnComplete))
    const showResult = isComplete || wasRejected

    if (!plan && !showResult) {
        return null
    }

    if (!showResult) {
        return <div className="my-2">{plan && <PlanCard plan={plan} id={`plan-${message.id}`} />}</div>
    }

    const statusIcon = isComplete && <IconCheckCircle className="mt-0.5 size-4 shrink-0 text-success" />
    const statusText = isComplete ? (
        <span className="text-success">Plan approved — proceeding with implementation</span>
    ) : (
        <span className="text-muted">(Plan rejected)</span>
    )

    return (
        <div className="my-2">
            {plan ? (
                <button
                    type="button"
                    onClick={() => setIsPlanExpanded((expanded) => !expanded)}
                    aria-expanded={isPlanExpanded}
                    className="flex items-start gap-2 rounded px-1 text-left hover:bg-fill-button-tertiary-hover"
                >
                    <IconChevronRight
                        className={`mt-1 size-3 shrink-0 text-muted transition-transform ${isPlanExpanded ? 'rotate-90' : ''}`}
                    />
                    {statusIcon}
                    {/* One text run, so a narrow row wraps it like a sentence instead of as two columns. */}
                    <span className="min-w-0 text-[13px]">
                        {statusText}{' '}
                        <span className="whitespace-nowrap text-muted">
                            · {isPlanExpanded ? 'hide plan' : 'show plan'}
                        </span>
                    </span>
                </button>
            ) : (
                <div className="flex items-start gap-2 px-1">
                    {statusIcon}
                    <span className="min-w-0 text-[13px]">{statusText}</span>
                </div>
            )}
            {plan && isPlanExpanded && (
                <div className="mt-2">
                    <PlanCard plan={plan} id={`plan-${message.id}`} />
                </div>
            )}
        </div>
    )
})

/** Grep / Glob / LS — result count on line 2, matched lines in the body. */
const SearchToolRenderer = memo(function SearchToolRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props
    const output = getContentText(message.content)
    const count = getResultCount(output)

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconSearch />}
            title={message.title || displayName || 'Search'}
            subtitle={output ? `${count} ${count === 1 ? 'result' : 'results'}` : undefined}
            body={output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

interface TodoItem {
    content: string
    status: string
}

function getTodos(rawInput: Record<string, unknown>): TodoItem[] {
    if (!Array.isArray(rawInput.todos)) {
        return []
    }
    return rawInput.todos.flatMap((todo): TodoItem[] =>
        todo && typeof todo === 'object' && typeof (todo as TodoItem).content === 'string'
            ? [{ content: (todo as TodoItem).content, status: asString((todo as TodoItem).status) }]
            : []
    )
}

/** TodoWrite — the agent's plan as a checklist, with the finished count on line 2. */
const TodoToolRenderer = memo(function TodoToolRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props
    const todos = getTodos(message.rawInput)
    const done = todos.filter((todo) => todo.status === 'completed').length

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconListCheck />}
            title={message.title || displayName || 'Tasks'}
            subtitle={todos.length > 0 ? `${done} of ${todos.length} done` : undefined}
            body={
                todos.length > 0 ? (
                    <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                        {todos.map((todo, index) => (
                            <li key={index} className="flex items-start gap-2 text-[13px] leading-5">
                                {todo.status === 'completed' ? (
                                    <IconCheckCircle className="mt-0.5 size-4 shrink-0 text-success" />
                                ) : todo.status === 'in_progress' ? (
                                    <IconArrowCircleRight className="mt-0.5 size-4 shrink-0" />
                                ) : (
                                    <IconCircleDashed className="mt-0.5 size-4 shrink-0 text-muted" />
                                )}
                                <span
                                    className={
                                        todo.status === 'completed'
                                            ? 'text-muted'
                                            : todo.status === 'in_progress'
                                              ? 'font-medium'
                                              : undefined
                                    }
                                >
                                    {todo.content}
                                </span>
                            </li>
                        ))}
                    </ul>
                ) : undefined
            }
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/**
 * Task / Agent — a delegated subagent run. The header reads `{subagent_type}: {description}`, and the
 * body carries the prompt the subagent was handed plus its returned output. The description lives only
 * in the title (not echoed as a subtitle or input dump), so the card no longer duplicates it.
 */
const SubagentToolRenderer = memo(function SubagentToolRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const subagentType = asString(message.rawInput.subagent_type)
    const description = asString(message.rawInput.description) || message.title || ''
    const prompt = asString(message.rawInput.prompt)
    const output = stripCodeFences(getContentText(message.content))
    // An echo-style subagent returns its prompt verbatim — don't render the same text twice.
    const showOutput = !!output && output.trim() !== prompt.trim()

    const title =
        subagentType && description ? `${subagentType}: ${description}` : subagentType || description || 'Subagent'

    const body =
        prompt || showOutput ? (
            <ToolBody>
                {prompt && <ToolOutput>{prompt}</ToolOutput>}
                {showOutput && (
                    <ToolBodySection divided={!!prompt}>
                        <ToolOutput>{output}</ToolOutput>
                    </ToolBodySection>
                )}
            </ToolBody>
        ) : undefined

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconRobot />}
            title={title}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/** WebFetch / WebSearch — linked URL (or query) on line 2, fetched content in the body. */
const FetchToolRenderer = memo(function FetchToolRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const url = asString(message.rawInput.url)
    const query = asString(message.rawInput.query)
    const output = stripCodeFences(getContentText(message.content))
    const isSearch = !url && !!query
    // Render the URL as plain mono text — not a highlighted, openable link.
    const target = url || query

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconGlobe />}
            title={message.title || (isSearch ? 'Web search' : 'Fetched')}
            subtitle={
                target ? (
                    <span className="font-mono" title={target}>
                        {truncateText(target, MAX_URL_LENGTH)}
                    </span>
                ) : undefined
            }
            body={output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/**
 * PostHog single-exec discovery verbs (`tools` / `search` / `info` / `schema`, plus the `unknown`
 * fallback). `getPostHogExecDisplay` turns the `command` into a friendly label ("List tools",
 * "Search tools", "Read <tool>", "Inspect <tool>.<field>") and an optional input preview; the
 * discovery output renders in the body. The `call` verb never reaches here — it resolves to its inner
 * tool's renderer instead.
 */
const PostHogExecRenderer = memo(function PostHogExecRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const display = getPostHogExecDisplay(message.rawInput)
    const input = display?.input
    const output = stripCodeFences(getContentText(message.content))

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconWrench />}
            title={display?.label || message.title || 'Run command'}
            subtitle={
                input ? (
                    <span className="font-mono" title={input}>
                        {truncateText(input, MAX_COMMAND_LENGTH)}
                    </span>
                ) : undefined
            }
            body={output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/**
 * Skill — a single line naming the invoked skill. Input and output stay viewable in the body exactly as
 * the generic card renders them; falls back to the generic card entirely when `skill` isn't a string.
 */
const SkillToolRenderer = memo(function SkillToolRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const skill = asString(message.rawInput.skill)
    if (!skill) {
        return <GenericMcpToolRenderer {...props} />
    }

    const hasInput = Object.keys(message.rawInput).length > 0
    const formattedInput = hasInput ? formatInput(message.rawInput) : ''
    const output = stripCodeFences(getContentText(message.content))
    const body =
        formattedInput || output ? (
            <ToolBody>
                {formattedInput && <ToolOutput>{formattedInput}</ToolOutput>}
                {output && (
                    <ToolBodySection divided={!!formattedInput}>
                        <ToolOutput>{output}</ToolOutput>
                    </ToolBodySection>
                )}
            </ToolBody>
        ) : undefined

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconMagicWand />}
            title={
                <span>
                    Skill <span className="font-mono">{skill}</span>
                </span>
            }
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/**
 * ToolSearch — a deferred-tool search (Claude's built-in, or a Pi MCP proxy search resolved onto this key),
 * rendered like PostHog's MCP tool search: a "Search tools" header with the query on the second line and
 * the matched tool schemas in the body. Falls back to the generic card when no query is present.
 */
const ToolSearchRenderer = memo(function ToolSearchRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const input = message.innerInput ?? message.rawInput
    const query = asString(input.query)
    if (!query) {
        return <GenericMcpToolRenderer {...props} />
    }
    const formattedInput = formatInput(input)
    const output = stripCodeFences(getContentText(message.content))
    const body =
        formattedInput || output ? (
            <ToolBody>
                {formattedInput && <ToolOutput>{formattedInput}</ToolOutput>}
                {output && (
                    <ToolBodySection divided={!!formattedInput}>
                        <ToolOutput>{output}</ToolOutput>
                    </ToolBodySection>
                )}
            </ToolBody>
        ) : undefined

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconSearch />}
            title="Search tools"
            subtitle={
                <span className="font-mono" title={query}>
                    {truncateText(query, MAX_COMMAND_LENGTH)}
                </span>
            }
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/**
 * Single lazy entry covering every Claude built-in plus the generic MCP fallback — mirrors the agent
 * UI's `ToolCallBlock` dispatch. Switches on the resolved tool name; anything unrecognised renders
 * through `GenericMcpToolRenderer`. Registered for each built-in key and as the registry's default.
 */
export const BuiltinToolRenderer = memo(function BuiltinToolRenderer(props: ToolRendererProps): JSX.Element {
    if (props.message.resolvedKey.startsWith('__posthog_exec_')) {
        return <PostHogExecRenderer {...props} />
    }
    const name = props.message.claudeToolName ?? props.message.resolvedKey
    switch (name) {
        case 'Bash':
        case 'BashOutput':
        case 'KillShell':
            return <BashToolRenderer {...props} />
        case 'Read':
        case 'NotebookRead':
            return <ReadToolRenderer {...props} />
        case 'Grep':
        case 'Glob':
        case 'LS':
            return <SearchToolRenderer {...props} />
        case 'Task':
        case 'Agent':
            return <SubagentToolRenderer {...props} />
        case 'WebFetch':
        case 'WebSearch':
            return <FetchToolRenderer {...props} />
        case 'Skill':
            return <SkillToolRenderer {...props} />
        case 'ToolSearch':
            return <ToolSearchRenderer {...props} />
        case 'TodoWrite':
            return <TodoToolRenderer {...props} />
        case 'ExitPlanMode':
            return <ExitPlanModeRenderer {...props} />
        default:
            return <GenericMcpToolRenderer {...props} />
    }
})
