import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardProps } from './types'

export function GenericSignalCard({ signal }: SignalCardProps): JSX.Element {
    return (
        <SignalCardShell signal={signal}>
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}
        </SignalCardShell>
    )
}
