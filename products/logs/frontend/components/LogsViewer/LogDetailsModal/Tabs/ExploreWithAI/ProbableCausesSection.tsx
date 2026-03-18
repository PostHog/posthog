import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { CONFIDENCE_CONFIG } from './constants'
import { ProbableCause } from './types'

export interface ProbableCausesSectionProps {
    causes: ProbableCause[]
}

export function ProbableCausesSection({ causes }: ProbableCausesSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2 p-2">
            {causes.map((cause, index) => (
                <div key={index} className="flex flex-col gap-1 p-2 bg-bg-light rounded">
                    <div className="flex items-center gap-2">
                        <span className="text-muted text-xs font-mono">{index + 1}.</span>
                        <Tooltip title="AI's confidence in this hypothesis">
                            <LemonTag type={CONFIDENCE_CONFIG[cause.confidence]?.type ?? 'muted'} size="small">
                                {CONFIDENCE_CONFIG[cause.confidence]?.label ?? cause.confidence}
                            </LemonTag>
                        </Tooltip>
                        <span className="font-medium text-sm">{cause.hypothesis}</span>
                    </div>
                    <p className="m-0 text-xs text-muted pl-6">{cause.reasoning}</p>
                </div>
            ))}
        </div>
    )
}
