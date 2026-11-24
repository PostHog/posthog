import { useValues } from 'kea'

import { LemonBanner, LemonCard, Spinner } from '@posthog/lemon-ui'

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

    if (healthFindings === null || healthChecks === null) {
        return experimentHealthLoading ? (
            <div className="flex items-center gap-2 py-8 text-secondary" data-attr="experiment-health-tab-loading">
                <Spinner />
                <span>Running the health checks</span>
            </div>
        ) : (
            <LemonBanner type="error">Couldn't load the health checks. Refresh the page to try again.</LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-2" data-attr="experiment-health-tab">
            <LemonCard hoverEffect={false} className="p-0">
                <HealthChecksPanel
                    checks={healthChecks}
                    findings={healthFindings}
                    // A server from before the setup was reported sends none, for example while a deploy rolls out.
                    setup={experimentHealth?.setup ?? null}
                    // A reset to draft keeps the previous exposure answer in the page, as for the checks.
                    exposures={isExperimentDraft ? null : (exposures ?? null)}
                    isDraft={isExperimentDraft}
                    exposureChecksMissing={healthExposureChecks === 'missing'}
                />
            </LemonCard>
            {healthExposureChecks === 'pending' && (
                <span className="flex items-center gap-1 text-secondary">
                    <Spinner className="text-sm" />
                    <span>Checking the exposures</span>
                </span>
            )}
        </div>
    )
}
