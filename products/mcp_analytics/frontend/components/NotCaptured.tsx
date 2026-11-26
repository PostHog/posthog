import { Link, Tooltip } from '@posthog/lemon-ui'

import type { InstrumentationFix } from '../instrumentationFixes'

export function NotCaptured({ reason, fix }: { reason: string; fix: InstrumentationFix }): JSX.Element {
    return (
        <Tooltip
            interactive
            title={
                <>
                    {reason}{' '}
                    <Link to={fix.docsUrl} target="_blank">
                        How to capture it
                    </Link>
                </>
            }
        >
            <span className="cursor-help whitespace-nowrap text-muted">Not captured</span>
        </Tooltip>
    )
}
