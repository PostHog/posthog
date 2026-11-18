import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { SetupFactsTable } from '../../setupInspector/SetupFactsTable'
import { experimentHealthDebugLogic } from './experimentHealthDebugLogic'
import { HealthDebugCheckResults } from './HealthDebugCheckResults'
import {
    CHECK_RESULTS_DESCRIPTION,
    CHECK_RESULTS_TITLE,
    EXPOSURES_INPUT_NOTE,
    HEALTH_DEBUG_DESCRIPTION,
    HEALTH_DEBUG_DOMAINS,
    HEALTH_DEBUG_TITLE,
    INPUTS_DESCRIPTION,
    INPUTS_TITLE,
} from './healthDebugCopy'
import { HealthDebugFlagTab } from './HealthDebugFlagTab'
import { HealthDebugProjectTab } from './HealthDebugProjectTab'
import { HEALTH_DEBUG_DOMAIN_LABELS, type HealthDebugDomain } from './healthDebugReport'
import { HealthDebugSection } from './HealthDebugSection'
import { QuillExperimentHealthDebug } from './QuillExperimentHealthDebug'

/** The staff-only experiment tab: what each health check concluded, and the inputs it read, by domain. */
export function ExperimentHealthDebug(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    if (todayRailNav && resultsRedesign) {
        return <QuillExperimentHealthDebug />
    }
    return <LemonExperimentHealthDebug />
}

function LemonExperimentHealthDebug(): JSX.Element {
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
                <p className="text-secondary text-sm mb-0">{EXPOSURES_INPUT_NOTE}</p>
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
                        {HEALTH_DEBUG_TITLE}
                        <LemonTag type="muted">Staff only</LemonTag>
                    </h3>
                    <p className="text-secondary text-sm mb-0">{HEALTH_DEBUG_DESCRIPTION}</p>
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
            <HealthDebugSection title={CHECK_RESULTS_TITLE} description={CHECK_RESULTS_DESCRIPTION}>
                <HealthDebugCheckResults />
            </HealthDebugSection>
            <HealthDebugSection title={INPUTS_TITLE} description={INPUTS_DESCRIPTION}>
                <LemonSegmentedButton
                    size="small"
                    value={activeDomain}
                    onChange={setActiveDomain}
                    options={HEALTH_DEBUG_DOMAINS.map((domain) => ({
                        value: domain,
                        label: HEALTH_DEBUG_DOMAIN_LABELS[domain],
                    }))}
                />
                {domainContent[activeDomain]}
            </HealthDebugSection>
        </div>
    )
}
