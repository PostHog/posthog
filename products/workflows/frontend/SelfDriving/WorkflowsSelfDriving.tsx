import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ScoutSummaryRow } from 'products/signals/frontend/inbox/components/config/scouts/ScoutSummaryRow'

import { SelfDrivingOptInCard } from './SelfDrivingOptInCard'
import { SelfDrivingSuggestionRow } from './SelfDrivingSuggestionRow'
import { workflowsSelfDrivingLogic } from './workflowsSelfDrivingLogic'

export function WorkflowsSelfDriving(): JSX.Element {
    const {
        availability,
        scoutConfigs,
        selfDrivingEnabled,
        suggestions,
        suggestionsFailed,
        turningOn,
        updatingScoutIds,
    } = useValues(workflowsSelfDrivingLogic)
    const { turnOnSelfDriving, updateScoutConfig } = useActions(workflowsSelfDrivingLogic)

    if (availability === 'unknown') {
        return <LemonSkeleton className="h-32 w-full max-w-3xl" />
    }

    if (availability === 'error') {
        return (
            <LemonBanner type="error" className="max-w-3xl">
                Couldn't load Self-driving. Refresh the page to try again, and if it keeps failing contact support.
            </LemonBanner>
        )
    }

    if (availability === 'unavailable') {
        return (
            <LemonBanner type="info" className="max-w-3xl">
                Self-driving isn't available for this project yet. It is rolling out to a small number of projects
                first.
            </LemonBanner>
        )
    }

    if (!selfDrivingEnabled) {
        return <SelfDrivingOptInCard onTurnOn={turnOnSelfDriving} turningOn={turningOn} />
    }

    const backUrl = urls.workflows('self-driving')

    return (
        <div className="flex flex-col gap-6">
            <section className="flex flex-col gap-2">
                <h3 className="mb-0">Scouts</h3>
                <p className="mb-0 text-secondary">
                    Each scout runs on its own schedule and changes nothing on its own. Turn one off to stop its
                    suggestions.
                </p>
                <div className="flex flex-col gap-2">
                    {(scoutConfigs ?? []).map((config) => (
                        <ScoutSummaryRow
                            key={config.id}
                            config={config}
                            onUpdate={updateScoutConfig}
                            updating={updatingScoutIds.includes(config.id)}
                        />
                    ))}
                </div>
            </section>
            <section className="flex flex-col gap-2">
                <h3 className="mb-0">Suggestions</h3>
                {suggestionsFailed ? (
                    <p className="mb-0 text-secondary">Couldn't load the suggestions. Refresh the page to try again.</p>
                ) : suggestions === null ? (
                    <LemonSkeleton className="h-16 w-full" repeat={2} />
                ) : suggestions.length === 0 ? (
                    <p className="mb-0 text-secondary">
                        No suggestions yet. The scout files one only when workflows reach the same people within a few
                        days of each other.
                    </p>
                ) : (
                    <div className="flex flex-col gap-2">
                        {suggestions.map((report) => (
                            <SelfDrivingSuggestionRow key={report.id} report={report} backUrl={backUrl} />
                        ))}
                    </div>
                )}
            </section>
        </div>
    )
}
