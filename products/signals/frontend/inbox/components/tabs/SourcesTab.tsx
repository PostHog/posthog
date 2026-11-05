import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { signalSourcesLogic } from '../../signalSourcesLogic'
import { SignalSourceProduct } from '../../types'
import { AgentsRoster } from '../config/AgentsRoster'
import { SourceAdminWarning } from '../config/SourceAdminWarning'
import { SourceCatalog } from '../config/SourceCatalog'
import { SettingsSection } from './SettingsSection'

export function SourcesTab(): JSX.Element {
    const { sourceConfigs } = useValues(signalSourcesLogic)
    const { loadSources, loadSourceConfigs, loadVisionScanners, loadProductDataEvents } = useActions(signalSourcesLogic)

    useEffect(() => {
        loadSources()
        loadSourceConfigs()
        loadVisionScanners()
        loadProductDataEvents()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-6">
            <SettingsSection
                title="Your sources"
                description="Each source watches for signals, and spins up an agent to look into them."
            >
                <SourceAdminWarning
                    sourceConfigs={sourceConfigs}
                    sourceProduct={SignalSourceProduct.SignalsScout}
                    label="Scouts"
                />
                <AgentsRoster />
            </SettingsSection>
            <SettingsSection
                title="Available sources"
                description="Connect a tool so self-driving can investigate its signals alongside your PostHog data."
            >
                <SourceCatalog />
            </SettingsSection>
        </div>
    )
}
