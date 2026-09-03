import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { addProductIntent } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

// One intent per variant per session: repeated copies of the same snippet are
// retries, not new adoption signals.
const scrapeIntentFired = new Set<string>()

function reportScrapeSnippetCopied(variant: 'docker' | 'kubernetes'): void {
    posthog.capture('metrics scrape agent snippet copied', { variant })
    if (scrapeIntentFired.has(variant)) {
        return
    }
    scrapeIntentFired.add(variant)
    void addProductIntent({
        product_type: ProductKey.METRICS,
        intent_context: ProductIntentContext.METRICS_SCRAPE_AGENT_SNIPPET_COPIED,
        metadata: { variant },
    })
}

/**
 * The metrics empty state's hero action: deploy the scrape agent against the
 * Prometheus endpoints the team already exposes. The SDK and OTLP paths live in
 * the docs link next to it.
 */
export function MetricsScrapeAgentSetup(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const [agentTab, setAgentTab] = useState<'docker' | 'kubernetes'>('docker')

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
        <div className="flex flex-col gap-1">
            <span className="text-xs text-tertiary">
                Already exposing Prometheus metrics? The scrape agent forwards them, no code changes needed:
            </span>
            <LemonTabs
                activeKey={agentTab}
                onChange={setAgentTab}
                size="small"
                tabs={[
                    {
                        key: 'docker' as const,
                        label: 'Docker',
                        content: (
                            <CodeSnippet language={Language.Bash} onCopy={() => reportScrapeSnippetCopied('docker')}>
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
    )
}
