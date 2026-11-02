import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { MarketingAnalyticsRecommendationStep } from '~/queries/schema/schema-general'

export function RecommendationSteps({ steps }: { steps: MarketingAnalyticsRecommendationStep[] }): JSX.Element {
    return (
        <ol className="m-0 flex list-decimal flex-col gap-2 py-2 pl-5">
            {steps.map((step, index) => (
                <li key={index}>
                    <span>{step.text}</span>
                    {step.copyValue && (
                        <div className="mt-1">
                            <CopyToClipboardInline
                                description="value"
                                iconSize="xsmall"
                                className="rounded border bg-surface-primary px-1.5 py-0.5 font-mono text-xs"
                                data-attr="marketing-recommendations-step-copy"
                            >
                                {step.copyValue}
                            </CopyToClipboardInline>
                        </div>
                    )}
                </li>
            ))}
        </ol>
    )
}
