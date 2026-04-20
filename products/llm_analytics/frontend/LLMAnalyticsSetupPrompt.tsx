import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

import { ProductKey } from '~/queries/schema/schema-general'

import { llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'

type Thing = 'generation' | 'trace'

export function LLMAnalyticsSetupPrompt({
    children,
    className,
    thing = 'generation',
}: {
    children: React.ReactNode
    thing?: Thing
    className?: string
}): JSX.Element {
    const { hasSentAiEvent, hasSentAiEventLoading } = useValues(llmAnalyticsSharedLogic)

    return hasSentAiEventLoading ? (
        <div className="flex justify-center">
            <Spinner />
        </div>
    ) : !hasSentAiEvent ? (
        <IngestionStatusCheck className={className} thing={thing} />
    ) : (
        <>{children}</>
    )
}

function IngestionStatusCheck({ className, thing }: { className?: string; thing: Thing }): JSX.Element {
    return (
        <ProductIntroduction
            productName="LLM analytics"
            thingName={`LLM ${thing}`}
            titleOverride={`No LLM ${thing} events have been detected!`}
            description="To use the LLM Analytics product, please instrument your LLM calls with the PostHog SDK."
            isEmpty={true}
            productKey={ProductKey.LLM_ANALYTICS}
            className={className}
            docsURL="https://posthog.com/docs/llm-analytics/installation"
        />
    )
}
