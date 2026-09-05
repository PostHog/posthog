import { useValues } from 'kea'

import { Section } from '../components/Section'
import { WindowComparisonCard } from '../components/WindowComparisonCard'
import { compactAgeLabel } from '../lib/format'
import { doraLogic } from './doraLogic'

export function DoraDeploymentHealth(): JSX.Element {
    const { dora, doraLoading } = useValues(doraLogic)
    const firstLoad = doraLoading && !dora

    return (
        <Section id="dora-metrics" title="Deployment health">
            <div className="@container">
                <div className="grid grid-cols-1 gap-3 @min-[48rem]:grid-cols-3">
                    <WindowComparisonCard
                        title="Deployment frequency"
                        tooltip="Successful deployments per day in the selected environment scope. Each regional deployment counts separately."
                        value={dora?.deployments_per_day}
                        previousValue={dora?.deployments_per_day_prev}
                        formatValue={(value) => `${value.toFixed(1)}/day`}
                        emptyText="No successful deployments in this window."
                        loading={firstLoad}
                    />
                    <WindowComparisonCard
                        title="Failed deployment share"
                        tooltip="Deployments with a failure or error status divided by deployments that reached an outcome. A change failure proxy: successful deploys that broke production are not counted because no incident data is linked."
                        value={dora?.failed_deployment_share}
                        previousValue={dora?.failed_deployment_share_prev}
                        formatValue={(value) => `${(value * 100).toFixed(1)}%`}
                        deltaUnit="pt"
                        goodWhenDown
                        emptyText="No deployments reached an outcome in this window."
                        loading={firstLoad}
                    />
                    <WindowComparisonCard
                        title="Failed deploy to next success"
                        tooltip="Median wait from a deployment's first failure status to the next successful deployment in the same environment. A time to restore proxy: recovery without a deploy is invisible, and unrecovered failures are excluded."
                        value={dora?.median_failed_deploy_to_next_success_seconds}
                        previousValue={dora?.median_failed_deploy_to_next_success_seconds_prev}
                        formatValue={compactAgeLabel}
                        goodWhenDown
                        emptyText="No failed deployment recovered in this window."
                        loading={firstLoad}
                    />
                </div>
            </div>
        </Section>
    )
}
