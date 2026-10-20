import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { SetupFactsTable } from '../../setupInspector/SetupFactsTable'
import { experimentHealthDebugLogic } from './experimentHealthDebugLogic'
import { HealthDebugCheckResults } from './HealthDebugCheckResults'
import { HealthDebugFlagTab } from './HealthDebugFlagTab'
import { HealthDebugProjectTab } from './HealthDebugProjectTab'
import { HEALTH_DEBUG_DOMAIN_LABELS, type HealthDebugDomain } from './healthDebugReport'
import { HealthDebugSection } from './HealthDebugSection'

const DOMAINS: HealthDebugDomain[] = ['experiment', 'flag', 'exposures', 'metrics', 'project', 'raw']

/** The staff-only experiment tab: what each health check concluded, and the inputs it read, by domain. */
export function ExperimentHealthDebug(): JSX.Element {
    const { experimentId } = useValues(experimentLogic)
    const logic = experimentHealthDebugLogic({ experimentId })
    const {
        activeDomain,
        healthDebugSummary,
        experimentFacts,
        metricFacts,
        exposureFacts,
        healthDebugRawData,
        healthInputsLoading,
    } = useValues(logic)
    const { setActiveDomain, loadHealthInputs } = useActions(logic)

    const domainContent: Record<HealthDebugDomain, JSX.Element> = {
        experiment: <SetupFactsTable facts={experimentFacts} />,
        flag: <HealthDebugFlagTab />,
        exposures: (
            <div className="flex flex-col gap-2">
                <p className="text-secondary text-sm mb-0">
                    The exposure query's cached answer that the zero-exposures, SRM and bias checks read on the server.
                </p>
                <SetupFactsTable facts={exposureFacts} />
            </div>
        ),
        metrics: <SetupFactsTable facts={metricFacts} />,
        project: <HealthDebugProjectTab />,
        raw: (
            <CodeSnippet language={Language.JSON} thing="health debug data" maxLinesWithoutExpansion={20}>
                {JSON.stringify(healthDebugRawData, null, 2)}
            </CodeSnippet>
        ),
    }

    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex flex-col gap-1">
                    <h3 className="flex items-center gap-2 mb-0">
                        Health checks debug
                        <LemonTag type="muted">Staff only</LemonTag>
                    </h3>
                    <p className="text-secondary text-sm mb-0">
                        What each health check concluded, and the inputs it read. Customers don't see this tab.
                    </p>
                </div>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconRefresh />}
                    loading={healthInputsLoading}
                    onClick={() => loadHealthInputs()}
                    data-attr="experiment-health-debug-reload"
                >
                    Reload inputs
                </LemonButton>
            </div>
            <SetupFactsTable facts={healthDebugSummary} />
            <HealthDebugSection
                title="Check results"
                description="One row per check. The buttons under Reads open the inputs the check reads."
            >
                <HealthDebugCheckResults />
            </HealthDebugSection>
            <HealthDebugSection title="Inputs" description="The values the checks read, grouped by domain.">
                <LemonSegmentedButton
                    size="small"
                    value={activeDomain}
                    onChange={setActiveDomain}
                    options={DOMAINS.map((domain) => ({ value: domain, label: HEALTH_DEBUG_DOMAIN_LABELS[domain] }))}
                />
                {domainContent[activeDomain]}
            </HealthDebugSection>
        </div>
    )
}
