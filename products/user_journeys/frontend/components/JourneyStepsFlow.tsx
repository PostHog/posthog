import { LemonBadge } from 'lib/lemon-ui/LemonBadge'

import type { JourneyStepApi } from '../generated/api.schemas'
import { JourneyStepSummary } from './JourneyStepSummary'

export function JourneyStepsFlow({ steps }: { steps: JourneyStepApi[] }): JSX.Element {
    return (
        <ol className="flex flex-col list-none p-0 m-0" data-attr="user-journey-steps-flow">
            {steps.map((step, index) => (
                <li key={index} className="flex gap-3 min-w-0">
                    <div className="flex flex-col items-center shrink-0">
                        <LemonBadge.Number count={index + 1} status="muted" size="medium" maxDigits={2} />
                        {index < steps.length - 1 ? <div className="w-px flex-1 bg-border my-1" /> : null}
                    </div>
                    <div className="min-w-0 flex-1 pb-4">
                        <JourneyStepSummary step={step} />
                    </div>
                </li>
            ))}
        </ol>
    )
}
