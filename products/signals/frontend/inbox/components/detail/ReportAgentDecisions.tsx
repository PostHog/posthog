import { type ReactNode, useState } from 'react'

import { ActivityDisclosure } from './ActivityDisclosure'

/**
 * Groups the agent's decisions under one disclosure, collapsed by default. The collapsed line lists
 * the current values, so a wrong value shows without expanding.
 */
export function ReportAgentDecisions({
    values,
    onToggleCollapsed,
    children,
}: {
    /** Current values in row order. Empty values are left out of the collapsed line. */
    values: (string | null | undefined)[]
    onToggleCollapsed?: (collapsed: boolean) => void
    children: ReactNode
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const summary = values.filter(Boolean).join(' · ')

    return (
        <ActivityDisclosure
            expanded={expanded}
            onChange={(next) => {
                setExpanded(next)
                onToggleCollapsed?.(!next)
            }}
            fullWidth
            className="-mx-2"
            label={
                <span className="flex min-w-0 flex-1 items-center gap-3">
                    <span className="shrink-0 text-secondary">Agent decisions</span>
                    {summary && <span className="ml-auto truncate font-normal text-default">{summary}</span>}
                </span>
            }
            expandedLabel={<span className="text-secondary">Agent decisions</span>}
        >
            <dl className="m-0 flex flex-col gap-2 pr-2 pl-7" data-attr="report-agent-decisions">
                {children}
            </dl>
        </ActivityDisclosure>
    )
}
