import { useEffect, useRef } from 'react'

import { IconLightBulb, IconPlug } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import type { MissingCapabilityReport } from './sessionMissingCapabilitiesLogic'
import { formatRelativeOffset } from './utils'

/** A report, or its suggested fix, in the session timeline. */
export function MissingCapabilityRow({
    report,
    sessionStart,
    focused = false,
    variant = 'report',
}: {
    report: MissingCapabilityReport
    sessionStart: string
    /** Scrolls into view. */
    focused?: boolean
    variant?: 'report' | 'suggestion'
}): JSX.Element {
    const suggestion = variant === 'suggestion'
    const ref = useRef<HTMLLIElement>(null)
    useEffect(() => {
        if (focused) {
            ref.current?.scrollIntoView({ block: 'nearest' })
        }
    }, [focused])
    return (
        <li
            ref={ref}
            className={cn(
                'relative flex flex-col gap-1 rounded border border-l-2 border-warning bg-warning-highlight px-2 py-1.5',
                focused && 'ring-2 ring-warning'
            )}
            data-attr={suggestion ? 'mcp-session-suggested-fix-row' : 'mcp-session-missing-capability-row'}
        >
            <div className="flex items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-1.5 font-semibold text-warning-dark">
                    {suggestion ? (
                        <IconLightBulb className="shrink-0 text-xs" />
                    ) : (
                        <IconPlug className="shrink-0 text-xs" />
                    )}
                    {suggestion ? 'Suggested fix' : 'Reported missing capability'}
                </div>
                <span className="whitespace-nowrap font-mono text-[11px] text-secondary">
                    {formatRelativeOffset(sessionStart, report.timestamp)}
                </span>
            </div>
            <div className="whitespace-pre-line pl-5 text-xs leading-snug">
                {suggestion ? report.suggestion : report.report}
            </div>
        </li>
    )
}
