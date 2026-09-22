import { IconExternal } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import type { SignalNode } from 'scenes/debug/signals/types'

import { SignalCardShell } from './SignalCardShell'

/**
 * Presentational shell for external-source signal cards (GitHub, Linear, Zendesk, pganalyze).
 * Captures the common anatomy: brand-icon header, optional title, markdown body, and a prominent external link.
 */
export function ExternalSignalCard({
    signal,
    title,
    children,
    link,
}: {
    signal: SignalNode
    /** Optional title shown in the header (e.g. issue number or identifier). */
    title?: React.ReactNode
    /** Body content — typically the signal description. If a string, rendered as markdown. */
    children?: React.ReactNode
    /** Primary external link-out. Always opens in a new tab. */
    link?: { to: string; label: string }
}): JSX.Element {
    return (
        <SignalCardShell signal={signal} label={title}>
            {typeof children === 'string' ? (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {children}
                </LemonMarkdown>
            ) : (
                children
            )}

            {link && (
                <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary mt-2">
                    <span className="flex-1" />
                    <Link to={link.to} target="_blank" className="flex items-center gap-1 text-xs font-medium shrink-0">
                        {link.label} <IconExternal className="size-3" />
                    </Link>
                </div>
            )}
        </SignalCardShell>
    )
}
