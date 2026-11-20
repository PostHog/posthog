import { cn } from 'lib/utils/css-classes'
import { percentage } from 'lib/utils/numbers'
import { getOrdinalSuffix } from 'lib/utils/strings'

import type { ToolJourney } from './toolReportQueries'

export interface JourneyFindings {
    errorSessions: number
    totalSessions: number
    /** Where the tool usually first appears, as a share of the charted journeys that include it. */
    position: { index: number; share: number } | null
    /** What usually follows the tool's first call. `null` means the session ended there. */
    next: { tool: string | null; share: number } | null
}

function mostCommon<K>(counts: Map<K, number>, total: number): { key: K; share: number } | null {
    let best: [K, number] | null = null
    for (const entry of counts) {
        if (!best || entry[1] > best[1]) {
            best = entry
        }
    }
    return best && total > 0 ? { key: best[0], share: best[1] / total } : null
}

export function journeyFindings(journey: ToolJourney, toolName: string): JourneyFindings {
    const positions = new Map<number, number>()
    const next = new Map<string | null, number>()
    let withTool = 0
    let withNext = 0
    for (const path of journey.paths) {
        const index = path.steps.indexOf(toolName)
        if (index < 0) {
            continue
        }
        withTool += path.count
        positions.set(index, (positions.get(index) ?? 0) + path.count)
        // The chart stops at its last column, so a call there has no known next step.
        if (index < path.steps.length - 1) {
            withNext += path.count
            const following = path.steps[index + 1]
            next.set(following, (next.get(following) ?? 0) + path.count)
        }
    }
    const position = mostCommon(positions, withTool)
    const nextStep = mostCommon(next, withNext)
    return {
        errorSessions: journey.errorSessions,
        totalSessions: journey.totalSessions,
        position: position && { index: position.key, share: position.share },
        next: nextStep && { tool: nextStep.key, share: nextStep.share },
    }
}

function Finding({
    tone,
    children,
}: {
    tone: 'danger' | 'success' | 'neutral'
    children: React.ReactNode
}): JSX.Element {
    return (
        <li className="flex items-baseline gap-2">
            <span
                className={cn(
                    'size-2 shrink-0 translate-y-[-1px] rounded-full',
                    tone === 'danger' ? 'bg-danger' : tone === 'success' ? 'bg-success' : 'bg-border-bold'
                )}
                aria-hidden
            />
            <span>{children}</span>
        </li>
    )
}

export function ToolJourneySummary({ journey, toolName }: { journey: ToolJourney; toolName: string }): JSX.Element {
    const { errorSessions, totalSessions, position, next } = journeyFindings(journey, toolName)
    const tool = <span className="font-semibold">{toolName}</span>

    return (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm" data-attr="mcp-tool-journey-summary">
            {errorSessions > 0 ? (
                <Finding tone="danger">
                    {errorSessions} of {totalSessions} sessions with {tool} hit an error (
                    {percentage(errorSessions / totalSessions, 0)}).
                </Finding>
            ) : (
                <Finding tone="success">
                    None of the {totalSessions} sessions with {tool} hit an error.
                </Finding>
            )}
            {position && (
                <Finding tone="neutral">
                    Agents most often call {tool}{' '}
                    {position.index === 0
                        ? 'first'
                        : `as their ${position.index + 1}${getOrdinalSuffix(position.index + 1)} tool`}{' '}
                    ({percentage(position.share, 0)} of the journeys below).
                </Finding>
            )}
            {next &&
                (next.tool === null ? (
                    <Finding tone="neutral">
                        Sessions most often end right after {tool} ({percentage(next.share, 0)}).
                    </Finding>
                ) : (
                    <Finding tone="neutral">
                        Next, agents most often call <span className="font-semibold">{next.tool}</span> (
                        {percentage(next.share, 0)}).
                    </Finding>
                ))}
        </ul>
    )
}
