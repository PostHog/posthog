import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

import { ProductKey } from '~/types'

import { llmAnalyticsLogic } from './llmAnalyticsLogic'

export function LLMAnalyticsSetupPrompt({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element {
    const { hasSentAiGenerationEvent, hasSentAiGenerationEventLoading } = useValues(llmAnalyticsLogic)

    return hasSentAiGenerationEventLoading ? (
        <div className="flex justify-center">
            <Spinner />
        </div>
    ) : !hasSentAiGenerationEvent ? (
        <IngestionStatusCheck className={className} />
    ) : (
        <>{children}</>
    )
}

function IngestionStatusCheck({ className }: { className?: string }): JSX.Element {
    return (
        <ProductIntroduction
            productName="LLM analytics"
            thingName="LLM generation"
            titleOverride="No LLM generation events have been detected!"
            description="To use the LLM Analytics product, please instrument your LLM calls with the PostHog SDK."
            isEmpty={true}
            productKey={ProductKey.LLM_ANALYTICS}
            className={className}
            docsURL="https://posthog.com/docs/llm-analytics/installation"
        />
    )
}
