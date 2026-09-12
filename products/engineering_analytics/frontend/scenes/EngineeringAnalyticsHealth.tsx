import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { ScopeBar, ScopeDateFilter, SourceScopeChip } from '../components/ScopeBar'
import { ScopePanel } from '../components/ScopePanel'
import { DoraDeploymentFrequency } from './DoraDeploymentFrequency'
import { DoraDeploymentHealth } from './DoraDeploymentHealth'
import { DoraLeadTimeSection } from './DoraLeadTimeSection'
import { doraLogic } from './doraLogic'

export function EngineeringAnalyticsHealth(): JSX.Element {
    const { notConnected, dora, doraLoading, doraFailed, selectedEnvironments, granularity, environmentOptions } =
        useValues(doraLogic)
    const { setEnvironments, setGranularity, loadDora } = useActions(doraLogic)
    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (doraFailed) {
        return <CIAnalyticsLoadError onRetry={loadDora} />
    }

    const deployDataMissing = !!dora && !dora.deploy_data_available

    return (
        <div className="flex flex-col gap-4">
            <ScopeBar repoSlot={<SourceScopeChip />} showDate={false} />
            {dora?.latest_deploy_status_at && (
                <span className="text-xs text-tertiary" data-attr="engineering-analytics-dora-freshness">
                    Latest deploy status synced {dayjs(dora.latest_deploy_status_at).fromNow()}.
                </span>
            )}
            {deployDataMissing && (
                <div data-attr="engineering-analytics-dora-no-deploy-data">
                    <LemonBanner type="info">
                        Deploy data isn't synced yet. Enable the deployments and deployment statuses endpoints on your
                        GitHub source to see DORA metrics.
                    </LemonBanner>
                </div>
            )}
            <ScopePanel
                busy={doraLoading && !!dora}
                controls={
                    <>
                        {!deployDataMissing && (
                            <div className="w-60 max-w-full" data-attr="engineering-analytics-dora-environment-select">
                                <LemonInputSelect
                                    size="small"
                                    mode="multiple"
                                    title="Environments"
                                    disablePrompting
                                    displayMode={selectedEnvironments.length > 3 ? 'count' : 'snacks'}
                                    value={selectedEnvironments}
                                    onChange={setEnvironments}
                                    options={environmentOptions}
                                    placeholder={doraLoading ? 'Loading environments…' : 'Production environments'}
                                    allowCustomValues={false}
                                />
                            </div>
                        )}
                        <ScopeDateFilter />
                        <LemonSelect
                            size="small"
                            value={granularity}
                            onChange={setGranularity}
                            options={[
                                { value: null, label: 'Group automatically' },
                                { value: 'hour' as const, label: 'Group by hour' },
                                { value: 'day' as const, label: 'Group by day' },
                                { value: 'week' as const, label: 'Group by week' },
                            ]}
                            data-attr="engineering-analytics-dora-granularity-select"
                        />
                    </>
                }
            >
                <DoraLeadTimeSection />
                <DoraDeploymentHealth />
                <DoraDeploymentFrequency />
            </ScopePanel>
        </div>
    )
}
