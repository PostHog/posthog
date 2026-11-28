import { IconBrowser, IconCursorClick } from '@posthog/icons'

import { LemonBadge } from 'lib/lemon-ui/LemonBadge'

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

export function JourneyStepsFlow({ steps }: { steps: JourneyStepApi[] }): JSX.Element {
    return (
        <ol className="flex flex-col list-none p-0 m-0" data-attr="user-journey-steps-flow">
            {steps.map((step, index) => (
                <li key={index} className="flex gap-3 min-w-0">
                    <div className="flex flex-col items-center shrink-0">
                        <LemonBadge.Number count={index + 1} status="muted" size="medium" maxDigits={2} />
                        {index < steps.length - 1 ? <div className="w-px flex-1 bg-border my-1" /> : null}
                    </div>
                    <div className="flex flex-col gap-1 min-w-0 flex-1 pb-4">
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
                </li>
            ))}
        </ol>
    )
}
