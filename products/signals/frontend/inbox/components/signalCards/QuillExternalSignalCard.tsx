import { IconExternal } from '@posthog/icons'

import type { SignalNode } from 'scenes/debug/signals/types'

import { QuillSignalCardLink } from './QuillSignalCardLink'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'

/** Quill sibling of `ExternalSignalCard`: the shared anatomy of GitHub, Linear, Zendesk and pganalyze cards. */
export function QuillExternalSignalCard({
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
        <QuillSignalCardShell signal={signal} label={title}>
            {typeof children === 'string' ? <QuillSignalCardMarkdown>{children}</QuillSignalCardMarkdown> : children}

            {link && (
                <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
                    <QuillSignalCardLink to={link.to} newTab>
                        {link.label}
                        <IconExternal />
                    </QuillSignalCardLink>
                </div>
            )}
        </QuillSignalCardShell>
    )
}
