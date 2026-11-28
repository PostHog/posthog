import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import {
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationStep,
} from '~/queries/schema/schema-general'

import { QuillRecommendationStepText } from './QuillRecommendationStepText'

export function QuillRecommendationSteps({
    steps,
    rule,
}: {
    steps: MarketingAnalyticsRecommendationStep[]
    rule: MarketingAnalyticsRecommendationRule
}): JSX.Element {
    return (
        <ol className="m-0 flex list-decimal flex-col gap-2 py-2 pl-5 text-xs whitespace-normal">
            {steps.map((step, index) => (
                <li key={index}>
                    <div className="flex flex-col items-start gap-1">
                        <QuillRecommendationStepText step={step} rule={rule} />
                        {step.copyValue && (
                            <CopyToClipboardInline
                                description="value"
                                explicitValue={step.copyValue}
                                className="rounded-sm border border-border bg-card px-1.5 py-0.5 font-mono text-xs"
                                data-attr="marketing-recommendations-step-copy"
                            >
                                {/* A list of keywords goes one per line, the way Google Ads takes a pasted list. */}
                                <span className="whitespace-pre-line">{step.copyValue}</span>
                            </CopyToClipboardInline>
                        )}
                    </div>
                </li>
            ))}
        </ol>
    )
}
