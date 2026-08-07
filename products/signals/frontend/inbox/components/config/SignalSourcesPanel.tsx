import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SessionAnalysisSetup } from '../../SessionAnalysisSetup'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { AgentsRoster } from './AgentsRoster'
import { DataSourceSetup } from './DataSourceSetup'

function BackLink({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={onClick} className="-ml-2 w-fit">
            Back
        </LemonButton>
    )
}

/**
 * Signal sources management: the per-source roster (each source watches for signals and
 * spins up work when something matters), plus the session-analysis and data-source setup
 * sub-flows that render inline (replacing the roster) when their flow is open. Hosted in
 * the Signal sources setup modal.
 */
export function SignalSourcesPanel(): JSX.Element {
    const { sessionAnalysisSetupOpen, dataSourceSetupSource } = useValues(signalSourcesLogic)
    const {
        loadSources,
        loadSourceConfigs,
        closeSessionAnalysisSetup,
        closeDataSourceSetup,
        onDataSourceSetupComplete,
    } = useActions(signalSourcesLogic)

    useEffect(() => {
        loadSources()
        loadSourceConfigs()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    if (dataSourceSetupSource !== null) {
        return (
            <div className="flex flex-col gap-3">
                <BackLink onClick={closeDataSourceSetup} />
                <DataSourceSetup source={dataSourceSetupSource} onComplete={() => onDataSourceSetupComplete()} />
            </div>
        )
    }

    if (sessionAnalysisSetupOpen) {
        return (
            <div className="flex flex-col gap-3">
                <BackLink onClick={closeSessionAnalysisSetup} />
                <SessionAnalysisSetup />
            </div>
        )
    }

    return <AgentsRoster />
}
