import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import * as xRayPng from '@posthog/brand/hoggies/png/x-ray'
import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { useInterval } from 'lib/hooks/useInterval'
import goImage from 'scenes/onboarding/legacy/sdks/logos/go.svg'
import javaImage from 'scenes/onboarding/legacy/sdks/logos/java.svg'
import nodejsImage from 'scenes/onboarding/legacy/sdks/logos/nodejs.svg'
import pythonImage from 'scenes/onboarding/legacy/sdks/logos/python.svg'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { tracingIngestionLogic } from './tracingIngestionLogic'

const HedgehogXRay = pngHoggie(xRayPng)

const FRAMEWORK_LINKS: { name: string; image?: string; docsLink: string }[] = [
    { name: 'Node.js', image: nodejsImage, docsLink: 'https://opentelemetry.io/docs/languages/js/' },
    { name: 'Python', image: pythonImage, docsLink: 'https://opentelemetry.io/docs/languages/python/' },
    { name: 'Java', image: javaImage, docsLink: 'https://opentelemetry.io/docs/languages/java/' },
    { name: 'Go', image: goImage, docsLink: 'https://opentelemetry.io/docs/languages/go/' },
    { name: 'Other', docsLink: 'https://opentelemetry.io/docs/languages/' },
]

const POLLING_INTERVAL_MS = 5000

export const TracingSetupPrompt = ({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element => {
    const { hasSpans, teamHasSpansLoading, teamHasSpansCheckFailed } = useValues(tracingIngestionLogic)
    const { currentTeam } = useValues(teamLogic)

    if ((teamHasSpansLoading && hasSpans === undefined) || !currentTeam) {
        return (
            <div className="flex justify-center">
                <Spinner />
            </div>
        )
    }

    if (teamHasSpansCheckFailed || hasSpans === undefined) {
        return <>{children}</>
    }

    if (!hasSpans) {
        return <NoSpansPrompt className={className} />
    }

    return <>{children}</>
}

const NoSpansPrompt = ({ className }: { className?: string }): JSX.Element | null => {
    const { addProductIntent } = useActions(teamLogic)
    const { hasSpans } = useValues(tracingIngestionLogic)
    const { loadTeamHasSpans } = useActions(tracingIngestionLogic)

    useEffect(() => {
        posthog.capture('tracing setup prompt viewed')
    }, [])

    useInterval(() => {
        if (!hasSpans) {
            loadTeamHasSpans()
        }
    }, POLLING_INTERVAL_MS)

    const onDocsLinkClick = (docsType: string): void => {
        posthog.capture('tracing onboarding docs clicked', { docs_type: docsType })
        addProductIntent({
            product_type: ProductKey.TRACING,
            intent_context: ProductIntentContext.TRACING_DOCS_VIEWED,
        })
    }

    return (
        <ProductIntroduction
            productName="Tracing"
            thingName="trace"
            titleOverride="You haven't sent any traces yet"
            description="PostHog tracing works with any OpenTelemetry-compatible client. You don't need any PostHog-specific packages – just use standard OpenTelemetry libraries to send spans via OTLP."
            isEmpty={true}
            productKey={ProductKey.TRACING}
            className={className}
            customHog={HedgehogXRay}
            actionElementOverride={
                <div className="flex flex-col items-start gap-4">
                    <p className="text-sm text-secondary m-0">
                        Read our{' '}
                        <Link to="https://posthog.com/docs/tracing" onClick={() => onDocsLinkClick('Tracing')}>
                            tracing docs
                        </Link>
                        , learn more about{' '}
                        <Link
                            to="https://opentelemetry.io/docs/what-is-opentelemetry/"
                            target="_blank"
                            disableDocsPanel
                            onClick={() => onDocsLinkClick('OpenTelemetry')}
                        >
                            OpenTelemetry
                        </Link>
                        , or pick a language to get started:
                    </p>
                    <div className="flex flex-wrap gap-2">
                        {FRAMEWORK_LINKS.map(({ name, image, docsLink }) => (
                            <LemonButton
                                key={name}
                                type="secondary"
                                size="small"
                                to={docsLink}
                                onClick={() => onDocsLinkClick(name)}
                                icon={
                                    image ? (
                                        <img src={image} alt="" aria-hidden="true" className="w-5 h-5" />
                                    ) : undefined
                                }
                            >
                                {name}
                            </LemonButton>
                        ))}
                    </div>
                    <div className="flex items-center gap-2 px-3 py-1.5 border border-accent rounded">
                        <div className="relative flex items-center justify-center">
                            <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                            <div className="w-2 h-2 bg-accent rounded-full" />
                        </div>
                        <span className="text-sm">Watching for traces</span>
                    </div>
                </div>
            }
        />
    )
}
