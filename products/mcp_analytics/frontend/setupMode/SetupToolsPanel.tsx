import { IconCheckCircle } from '@posthog/icons'
import { LemonCard, LemonTag, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { MCPServerTools } from './setupMode'

const COPY = {
    title: 'Your tools',
    tag: 'from your server',
    loading: 'Loading your tools',
    failed: "Couldn't load your tools. This panel tries again in a few seconds.",
    empty: 'Your tools show up here once your agent lists them.',
    called: 'called',
    progress: (called: number, total: number) => `${called} of ${total} ${total === 1 ? 'tool' : 'tools'} called`,
    more: (count: number) => `${count} more`,
}

const MAX_ROWS = 8

function ToolRow({ name, called }: { name: string; called: boolean }): JSX.Element {
    return (
        <li className="flex min-w-0 items-center gap-2 py-1">
            {called ? (
                <IconCheckCircle className="size-4 shrink-0 text-success" aria-hidden="true" />
            ) : (
                <span className="size-4 shrink-0 rounded-full border-2 border-secondary" aria-hidden="true" />
            )}
            <span className={cn('min-w-0 truncate font-mono text-xs', !called && 'text-secondary')} title={name}>
                {name}
            </span>
            {called ? <span className="sr-only">{COPY.called}</span> : null}
        </li>
    )
}

function ToolsBody({ tools, failed }: { tools: MCPServerTools | null; failed: boolean }): JSX.Element {
    if (tools === null) {
        return failed ? (
            <p className="m-0 text-xs text-secondary">{COPY.failed}</p>
        ) : (
            <div className="flex items-center gap-2 text-xs text-secondary">
                <Spinner className="text-sm" />
                {COPY.loading}
            </div>
        )
    }
    // Before any client lists the tools, the ones already called are the only names we know.
    const names = tools.listed ?? tools.called
    if (names.length === 0) {
        return <p className="m-0 text-xs text-secondary">{COPY.empty}</p>
    }
    const called = new Set(tools.called)
    // Called tools first, so a check never hides past the last row.
    const rows = [...names.filter((name) => called.has(name)), ...names.filter((name) => !called.has(name))]
    const hidden = rows.length - MAX_ROWS
    return (
        <>
            {tools.listed ? (
                <span className="text-xs text-secondary">
                    {COPY.progress(tools.listed.filter((name) => called.has(name)).length, tools.listed.length)}
                </span>
            ) : null}
            <ul className="m-0 flex list-none flex-col p-0">
                {rows.slice(0, MAX_ROWS).map((name) => (
                    <ToolRow key={name} name={name} called={called.has(name)} />
                ))}
            </ul>
            {hidden > 0 ? <span className="text-xs text-secondary">{COPY.more(hidden)}</span> : null}
        </>
    )
}

/** The tools the user's server offers, with the ones agents already called checked off. */
export function SetupToolsPanel({ tools, failed }: { tools: MCPServerTools | null; failed: boolean }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4">
            <div className="flex items-center justify-between gap-2">
                <span className="text-base font-semibold">{COPY.title}</span>
                <LemonTag size="small" type="success">
                    {COPY.tag}
                </LemonTag>
            </div>
            <ToolsBody tools={tools} failed={failed} />
        </LemonCard>
    )
}
