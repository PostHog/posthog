import { LemonTag } from '@posthog/lemon-ui'
import { JSX } from 'react'

import { formatTokensCompact } from '../lib/contextColors'
import { IconRefresh } from '../primitives/icons'

interface CompactBoundaryViewProps {
    trigger: 'manual' | 'auto'
    preTokens: number
    contextSize?: number
}

export function CompactBoundaryView({ trigger, preTokens, contextSize }: CompactBoundaryViewProps): JSX.Element {
    const tokensCompact = formatTokensCompact(preTokens)
    const percent = contextSize && contextSize > 0 ? Math.round((preTokens / contextSize) * 100) : null

    return (
        <div className="my-1 border-l-2 border-accent py-1 pl-3">
            <div className="flex items-center gap-2">
                <IconRefresh className="text-accent" style={{ fontSize: 14 }} />
                <span className="text-[13px] text-muted">Conversation compacted</span>
                <LemonTag size="small" type={trigger === 'auto' ? 'warning' : 'highlight'}>
                    {trigger}
                </LemonTag>
                <span className="text-[13px] text-muted">
                    {percent !== null
                        ? `(${percent}% of context · ~${tokensCompact} tokens summarized)`
                        : `(~${tokensCompact} tokens summarized)`}
                </span>
            </div>
        </div>
    )
}
