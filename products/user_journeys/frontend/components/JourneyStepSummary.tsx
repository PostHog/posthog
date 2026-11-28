import { IconBrowser, IconCursorClick } from '@posthog/icons'

import type { JourneyStepApi } from '../generated/api.schemas'
import { describeUrlMatching } from '../journeySteps'

function StepDetail({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex gap-1 min-w-0 text-xs">
            <span className="text-secondary shrink-0">{label}</span>
            <span className="font-mono truncate" title={value}>
                {value}
            </span>
        </div>
    )
}

/** What one step matches: its type, then the URL or the element it looks for. */
export function JourneyStepSummary({ step }: { step: JourneyStepApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-0">
            <div className="flex items-center gap-1 font-semibold">
                {step.type === 'pageview' ? (
                    <IconBrowser className="text-secondary shrink-0" />
                ) : (
                    <IconCursorClick className="text-secondary shrink-0" />
                )}
                <span>{step.type === 'pageview' ? 'Pageview' : 'Click'}</span>
            </div>
            {step.type === 'pageview' ? (
                <StepDetail label={describeUrlMatching(step.url_matching)} value={step.url} />
            ) : (
                <>
                    <StepDetail label="Selector" value={step.selector} />
                    {step.text ? <StepDetail label="Text is" value={step.text} /> : null}
                    {step.href ? <StepDetail label="Link to" value={step.href} /> : null}
                    {step.url ? (
                        <StepDetail
                            label={`On page where ${describeUrlMatching(step.url_matching)}`}
                            value={step.url}
                        />
                    ) : null}
                </>
            )}
        </div>
    )
}
