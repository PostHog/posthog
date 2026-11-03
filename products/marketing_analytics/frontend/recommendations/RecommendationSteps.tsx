import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { MarketingAnalyticsRecommendationStep } from '~/queries/schema/schema-general'

import { RecommendationStepText } from './RecommendationStepText'

export function RecommendationSteps({ steps }: { steps: MarketingAnalyticsRecommendationStep[] }): JSX.Element {
    return (
        <ol className="m-0 flex list-decimal flex-col gap-2 py-2 pl-5">
            {steps.map((step, index) => (
                <li key={index}>
                    <RecommendationStepText step={step} />
                    {step.copyValue && (
                        <div className="mt-1">
                            <CopyToClipboardInline
                                description="value"
                                explicitValue={step.copyValue}
                                iconSize="xsmall"
                                className="rounded border bg-surface-primary px-1.5 py-0.5 font-mono text-xs"
                                data-attr="marketing-recommendations-step-copy"
                            >
                                {/* A list of keywords goes one per line, the way Google Ads takes a pasted list. */}
                                <span className="whitespace-pre-line">{step.copyValue}</span>
                            </CopyToClipboardInline>
                        </div>
                    )}
                </li>
            ))}
        </ol>
    )
}
