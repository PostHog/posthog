import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import * as greekPng from '@posthog/brand/hoggies/png/greek'
import { LemonButton, LemonTabs, Link, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { useInterval } from 'lib/hooks/useInterval'
import { apiHostOrigin } from 'lib/utils/apiHost'
import javascriptImage from 'scenes/onboarding/shared/logos/javascript_web.svg'
import nodejsImage from 'scenes/onboarding/shared/logos/nodejs.svg'
import pythonImage from 'scenes/onboarding/shared/logos/python.svg'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { metricsIngestionLogic } from '../metricsIngestionLogic'

const HedgehogGreek = pngHoggie(greekPng)

// The SDK paths come first: a product engineer on a PaaS reaches for the SDK they
// already have, where the scrape agent below needs infra they may not run. The
// agent's own Docker and Kubernetes paths are the tabbed snippets, not links.
const FRAMEWORK_LINKS: { name: string; image?: string; docsLink: string }[] = [
    {
        name: 'JavaScript',
        image: javascriptImage,
        docsLink: 'https://posthog.com/docs/metrics/installation/javascript',
    },
    { name: 'Node.js', image: nodejsImage, docsLink: 'https://posthog.com/docs/metrics/installation/nodejs' },
    { name: 'Python', image: pythonImage, docsLink: 'https://posthog.com/docs/metrics/installation/python' },
    { name: 'Other', docsLink: 'https://posthog.com/docs/metrics/installation/other' },
]

const POLLING_INTERVAL_MS = 5000

export const MetricsSetupPrompt = ({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element => {
    const { hasMetrics, teamHasMetricsLoading, teamHasMetricsCheckFailed } = useValues(metricsIngestionLogic)
    const { currentTeam } = useValues(teamLogic)

    if ((teamHasMetricsLoading && hasMetrics === undefined) || !currentTeam) {
        return (
            <div className="flex justify-center">
                <Spinner />
            </div>
        )
    }

    if (teamHasMetricsCheckFailed || hasMetrics === undefined) {
        return <>{children}</>
    }

    if (!hasMetrics) {
        return <NoMetricsPrompt className={className} />
    }

    return <>{children}</>
}

const NoMetricsPrompt = ({ className }: { className?: string }): JSX.Element | null => {
    const { addProductIntent } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { hasMetrics } = useValues(metricsIngestionLogic)
    const { loadTeamHasMetrics, reportScrapeSnippetCopied } = useActions(metricsIngestionLogic)
    const [agentTab, setAgentTab] = useState<'docker' | 'kubernetes'>('docker')

    useEffect(() => {
        posthog.capture('metrics setup prompt viewed')
    }, [])

    useInterval(() => {
        if (!hasMetrics) {
            loadTeamHasMetrics()
        }
    }, POLLING_INTERVAL_MS)

    const onDocsLinkClick = (docsType: string): void => {
        posthog.capture('metrics onboarding docs clicked', { docs_type: docsType })
        addProductIntent({
            product_type: ProductKey.METRICS,
            intent_context: ProductIntentContext.METRICS_DOCS_VIEWED,
        })
    }

    const apiKey = currentTeam?.api_token ?? '<your project API key>'
    const dockerSnippet = [
        'docker run -d --name posthog-metrics-agent \\',
        `  -e POSTHOG_API_KEY=${apiKey} \\`,
        `  -e POSTHOG_HOST=${apiHostOrigin()} \\`,
        '  -e SCRAPE_TARGETS=your-app:9090 \\',
        '  posthog/metrics-agent:latest',
    ].join('\n')
    const helmSnippet = [
        'helm install posthog-metrics-agent \\',
        '  oci://ghcr.io/posthog/charts/posthog-metrics-agent \\',
        `  --set posthog.apiKey=${apiKey} \\`,
        `  --set posthog.host=${apiHostOrigin()}`,
        '',
        '# then annotate the pods you want scraped:',
        '#   prometheus.io/scrape: "true"',
        '#   prometheus.io/port: "9090"',
    ].join('\n')

    return (
        <ProductIntroduction
            productName="Metrics"
            thingName="metric"
            titleOverride="You haven't sent any metrics yet"
            description="Send metrics from the PostHog SDK you already have, from any OpenTelemetry-compatible client over OTLP, or by scraping the Prometheus endpoints you already expose."
            isEmpty={true}
            productKey={ProductKey.METRICS}
            className={className}
            customHog={HedgehogGreek}
            actionElementOverride={
                <div className="flex flex-col items-start gap-4">
                    <p className="text-sm text-secondary m-0">
                        Read our{' '}
                        <Link to="https://posthog.com/docs/metrics" onClick={() => onDocsLinkClick('Metrics')}>
                            metrics docs
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
                    <div className="flex flex-col gap-1 w-full max-w-160">
                        <h5 className="m-0">Or scrape your existing Prometheus metrics</h5>
                        <p className="text-sm text-secondary m-0">
                            Already exposing Prometheus metrics? Deploy the PostHog metrics agent in your infra and it
                            forwards them for you, no code changes needed. Counters and histograms with OpenMetrics
                            exemplars get clickable trace links automatically.
                        </p>
                        <LemonTabs
                            activeKey={agentTab}
                            onChange={(key) => {
                                setAgentTab(key)
                                onDocsLinkClick(key === 'docker' ? 'agent-docker' : 'agent-helm')
                            }}
                            tabs={[
                                {
                                    key: 'docker' as const,
                                    label: 'Docker',
                                    content: (
                                        <CodeSnippet
                                            language={Language.Bash}
                                            onCopy={() => reportScrapeSnippetCopied('docker')}
                                        >
                                            {dockerSnippet}
                                        </CodeSnippet>
                                    ),
                                },
                                {
                                    key: 'kubernetes' as const,
                                    label: 'Kubernetes',
                                    content: (
                                        <CodeSnippet
                                            language={Language.Bash}
                                            onCopy={() => reportScrapeSnippetCopied('kubernetes')}
                                        >
                                            {helmSnippet}
                                        </CodeSnippet>
                                    ),
                                },
                            ]}
                        />
                    </div>
                    <div className="flex items-center gap-2 px-3 py-1.5 border border-accent rounded">
                        <div className="relative flex items-center justify-center">
                            <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                            <div className="w-2 h-2 bg-accent rounded-full" />
                        </div>
                        <span className="text-sm">Watching for metrics</span>
                    </div>
                </div>
            }
        />
    )
}
