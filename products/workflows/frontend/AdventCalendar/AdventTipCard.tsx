import { IconLightBulb } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import type { AdventTip } from './adventContent'

export interface AdventTipCardProps {
    tip: AdventTip
    onLinkClick: () => void
}

export function AdventTipCard({ tip, onLinkClick }: AdventTipCardProps): JSX.Element {
    return (
        <div
            className="flex flex-col gap-1 rounded border border-primary bg-surface-primary p-2 text-left text-xs"
            data-attr="advent-tip"
        >
            <span className="flex items-center gap-1 font-semibold text-secondary">
                <IconLightBulb />
                {tip.kind}
            </span>
            <span>{tip.text}</span>
            {tip.link && (
                <Link to={tip.link.url} target="_blank" data-attr="advent-tip-link" onClick={onLinkClick}>
                    {tip.link.label}
                </Link>
            )}
        </div>
    )
}
