import { useValues } from 'kea'

import { LemonBanner, LemonCard } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { HealthChecksPanel } from './HealthChecksPanel'

export function ExperimentHealthTab(): JSX.Element {
    const {
        experimentHealth,
        healthFindings,
        healthChecks,
        healthExposureChecks,
        isExperimentDraft,
        experimentHealthLoading,
        exposures,
    } = useValues(experimentLogic)

    const checksLoading = healthFindings === null || healthChecks === null
    if (checksLoading && !experimentHealthLoading) {
        return <LemonBanner type="error">Couldn't load the health checks. Refresh the page to try again.</LemonBanner>
    }

    return (
        <div data-attr="experiment-health-tab">
            <LemonCard hoverEffect={false} className="p-0">
                <HealthChecksPanel
                    checks={healthChecks ?? []}
                    findings={healthFindings ?? []}
                    checksLoading={checksLoading}
                    // A server from before the setup was reported sends none, for example while a deploy rolls out.
                    setup={experimentHealth?.setup ?? null}
                    // A reset to draft keeps the previous exposure answer in the page, as for the checks.
                    exposures={isExperimentDraft ? null : (exposures ?? null)}
                    isDraft={isExperimentDraft}
                    exposureChecks={healthExposureChecks}
                />
            </LemonCard>
        </div>
    )
}
