import { useMountedLogic, useValues } from 'kea'
import { useRef } from 'react'

import { IconCheckCircle, IconPullRequest } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { inboxOnboardingLogic } from '../../logics/inboxOnboardingLogic'
import { scoutFleetLogic } from '../../logics/scoutFleetLogic'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../../types'
import { InboxSetupIncomplete } from './InboxSetupIncomplete'
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
    const { isSetupLoaded, isSelfDrivingSetUp, isWizardRunning, isWizardStateResolved, isRefetching, hasExistingWork } =
        useValues(inboxOnboardingLogic)
    const enabledSources = uniqueEnabledSources(sourceConfigs)
    const enabledScouts = (scoutConfigs ?? []).filter((scout) => scout.enabled && scout.emit)
    const visibleSources = enabledSources.slice(0, MAX_VISIBLE_ITEMS)
    const visibleScouts = enabledScouts.slice(0, MAX_VISIBLE_ITEMS)
    const sourcesLoading = sourceConfigs === null || sourceConfigsLoading
    const scoutsLoading = scoutConfigs === null || scoutConfigsLoading

    // A setup run that ends without enabling anything leaves this surface with nothing to wait for,
    // and the welcome prompt that carries the setup command stays suppressed for the rest of the
    // session once "Set up manually" has been pressed. Read from the same verdict the scene decides
    // the onboarding with, not from the lists below: those exclude a non-emitting scout and a
    // Replay Vision scanner, so a project watching through either would be told setup is unfinished.
    // The same two holds the scene applies: before the detector reports, `isWizardRunning === false`
    // only means nobody has asked yet, and a refetch in flight leaves every config on the value it
    // had before the run that is about to land.
    const isSetupVerdictSettled = isSetupLoaded && isWizardStateResolved && !isRefetching
    // Keep the last settled answer through those windows instead of swapping the surface for one
    // request round trip: the copy-the-command flow comes back to this tab, which refetches.
    const setupIsUnfinished = useRef(false)
    // Work elsewhere in the inbox means the scene already shows the dismissible paused banner, which
    // carries the same command with the diagnosis that fits a team who set self-driving up and then
    // turned it off. One empty tab under that banner is not a reason to say setup never finished.
    if (isSetupVerdictSettled) {
        setupIsUnfinished.current = !isSelfDrivingSetUp && !isWizardRunning && !hasExistingWork
    }
    if (setupIsUnfinished.current) {
        return <InboxSetupIncomplete />
    }

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
                        <Link
                            to={urls.inbox('settings')}
                            // pinned: analytics and UI tests can depend on these overflow-link selectors.
                            data-attr="inbox-waiting-signal-sources-more"
                            className="border-t border-primary px-1 pt-3 text-xs text-tertiary no-underline hover:text-primary focus-visible:text-primary"
                        >
                            And {enabledSources.length - MAX_VISIBLE_ITEMS} more
                        </Link>
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
                        <Link
                            to={urls.inbox('scouts')}
                            data-attr="inbox-waiting-scouts-more"
                            className="border-t border-primary px-1 pt-3 text-xs text-tertiary no-underline hover:text-primary focus-visible:text-primary"
                        >
                            And {enabledScouts.length - MAX_VISIBLE_ITEMS} more
                        </Link>
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
