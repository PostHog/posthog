import { IconExternal } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { genericSignalLink } from '../../utils/signalLinks'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardProps } from './types'

/**
 * Fallback card for a source without a dedicated renderer, or a payload that doesn't satisfy its
 * renderer's guard. Under the redesign it still links out to the underlying object whenever the
 * signal identifies it.
 */
export function GenericSignalCard({ signal }: SignalCardProps): JSX.Element {
    const redesign = useFeatureFlag('INBOX_REDESIGN')
    const link = redesign ? genericSignalLink(signal) : null
    return (
        <SignalCardShell signal={signal}>
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}
            {link && (
                <div className="flex items-center mt-2">
                    <span className="flex-1" />
                    <Link
                        to={link.to}
                        target={link.external ? '_blank' : undefined}
                        className="flex items-center gap-1 text-xs font-medium shrink-0"
                    >
                        {link.label} <IconExternal className="size-3" />
                    </Link>
                </div>
            )}
        </SignalCardShell>
    )
}
