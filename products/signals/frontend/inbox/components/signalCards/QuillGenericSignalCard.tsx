import { IconExternal } from '@posthog/icons'

import { genericSignalLink } from '../../utils/signalLinks'
import { QuillSignalCardLink } from './QuillSignalCardLink'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import type { SignalCardProps } from './types'

/**
 * Quill sibling of `GenericSignalCard`, the fallback for a source without a dedicated renderer, or a
 * payload that doesn't satisfy its renderer's guard. It still links out whenever the signal identifies the object.
 */
export function QuillGenericSignalCard({ signal }: SignalCardProps): JSX.Element {
    const link = genericSignalLink(signal)
    return (
        <QuillSignalCardShell signal={signal}>
            {signal.content && <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>}
            {link && (
                <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
                    <QuillSignalCardLink to={link.to} newTab={link.external}>
                        {link.label}
                        <IconExternal />
                    </QuillSignalCardLink>
                </div>
            )}
        </QuillSignalCardShell>
    )
}
