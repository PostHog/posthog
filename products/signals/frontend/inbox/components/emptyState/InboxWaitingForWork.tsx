import { useMountedLogic, useValues } from 'kea'

import { IconCheckCircle, IconPullRequest } from '@posthog/icons'

import { inboxOnboardingLogic } from '../../logics/inboxOnboardingLogic'
import { scoutFleetLogic } from '../../logics/scoutFleetLogic'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../../types'
import { InstallingFlowRow } from './InstallingFlowRow'
import { ScoutFlowRow } from './ScoutFlowRow'
import { SignalSourceFlowRow } from './SignalSourceFlowRow'

const MAX_VISIBLE_ITEMS = 3

function uniqueEnabledSources(sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig[] {
    const seenProducts = new Set<string>()
    return (sourceConfigs ?? []).filter((source) => {
        if (
            !source.enabled ||
            (source.source_product === SignalSourceProduct.SignalsScout &&
                source.source_type === SignalSourceType.CrossSourceIssue) ||
            // Retired: the row can outlive the feature until the cleanup migration runs.
            (source.source_product === SignalSourceProduct.SessionReplay &&
                source.source_type === SignalSourceType.SessionAnalysisCluster) ||
            seenProducts.has(source.source_product)
        ) {
            return false
        }
        seenProducts.add(source.source_product)
        return true
    })
}

export function InboxWaitingForWork(): JSX.Element {
    useMountedLogic(signalSourcesLogic)
    useMountedLogic(scoutFleetLogic)

    const { sourceConfigs, sourceConfigsLoading } = useValues(signalSourcesLogic)
    const { scoutConfigs, scoutConfigsLoading } = useValues(scoutFleetLogic)
    const { isWizardRunning } = useValues(inboxOnboardingLogic)
    const enabledSources = uniqueEnabledSources(sourceConfigs)
    const enabledScouts = (scoutConfigs ?? []).filter((scout) => scout.enabled && scout.emit)
    const visibleSources = enabledSources.slice(0, MAX_VISIBLE_ITEMS)
    const visibleScouts = enabledScouts.slice(0, MAX_VISIBLE_ITEMS)
    const sourcesLoading = sourceConfigs === null || sourceConfigsLoading
    const scoutsLoading = scoutConfigs === null || scoutConfigsLoading

    return (
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-7 py-6">
            <div className="flex flex-col items-center gap-2 text-center">
                <h2 className="m-0 text-lg font-semibold">Your agents are working in the background</h2>
                <p className="m-0 max-w-xl text-sm text-tertiary">
                    Your signal sources and scouts are running in the background. When they find something actionable, a
                    pull request will appear here.
                </p>
            </div>

            <div className="grid items-start gap-8 md:grid-cols-2">
                <section className="flex flex-col">
                    <div className="flex items-center justify-between gap-2 border-b border-primary px-1 pb-3">
                        <div>
                            <h3 className="m-0 text-sm font-semibold">Signal sources</h3>
                            <p className="m-0 text-xs text-tertiary">Events that start an investigation</p>
                        </div>
                        <span
                            className={`flex items-center gap-1 text-xs ${isWizardRunning ? 'text-warning' : 'text-success'}`}
                        >
                            {isWizardRunning ? (
                                'Installing'
                            ) : sourcesLoading ? (
                                'Loading'
                            ) : (
                                <>
                                    <IconCheckCircle className="size-3.5" />
                                    {enabledSources.length} active
                                </>
                            )}
                        </span>
                    </div>
                    <div className="flex flex-col gap-2">
                        {visibleSources.map((source) => (
                            <SignalSourceFlowRow key={source.id} source={source} />
                        ))}
                        {isWizardRunning ? <InstallingFlowRow type="source" /> : null}
                        {!sourcesLoading && !isWizardRunning && visibleSources.length === 0 ? (
                            <p className="m-0 p-3 text-xs text-tertiary">No signal sources are active.</p>
                        ) : null}
                    </div>
                    {enabledSources.length > MAX_VISIBLE_ITEMS ? (
                        <div className="border-t border-primary px-1 pt-3 text-xs text-tertiary">
                            And {enabledSources.length - MAX_VISIBLE_ITEMS} more
                        </div>
                    ) : null}
                </section>

                <section className="flex flex-col">
                    <div className="flex items-center justify-between gap-2 border-b border-primary px-1 pb-3">
                        <div>
                            <h3 className="m-0 text-sm font-semibold">Scouts</h3>
                            <p className="m-0 text-xs text-tertiary">Scheduled checks across your data</p>
                        </div>
                        <span
                            className={`flex items-center gap-1 text-xs ${isWizardRunning ? 'text-warning' : 'text-success'}`}
                        >
                            {isWizardRunning ? (
                                'Installing'
                            ) : scoutsLoading ? (
                                'Loading'
                            ) : (
                                <>
                                    <IconCheckCircle className="size-3.5" />
                                    {enabledScouts.length} active
                                </>
                            )}
                        </span>
                    </div>
                    <div className="flex flex-col gap-2">
                        {visibleScouts.map((scout) => (
                            <ScoutFlowRow key={scout.id} scout={scout} />
                        ))}
                        {isWizardRunning ? <InstallingFlowRow type="scout" /> : null}
                        {!scoutsLoading && !isWizardRunning && visibleScouts.length === 0 ? (
                            <p className="m-0 p-3 text-xs text-tertiary">No scouts are active.</p>
                        ) : null}
                    </div>
                    {enabledScouts.length > MAX_VISIBLE_ITEMS ? (
                        <div className="border-t border-primary px-1 pt-3 text-xs text-tertiary">
                            And {enabledScouts.length - MAX_VISIBLE_ITEMS} more
                        </div>
                    ) : null}
                </section>
            </div>

            <div className="flex items-center justify-center gap-2 text-sm text-secondary">
                <IconPullRequest className="text-lg" />
                Pull requests will appear here when a finding is ready to ship.
            </div>
        </div>
    )
}
