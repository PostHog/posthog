import { useActions } from 'kea'
import { useEffect } from 'react'

import { signalSourcesLogic } from '../../signalSourcesLogic'
import { AgentsRoster } from './AgentsRoster'

/**
 * Signal sources management: the per-source roster (each source watches for signals and
 * spins up an agent to look into them). Adding a source opens the catalog modal from the
 * roster. Hosted in the Signal sources setup modal and the Settings tab.
 */
export function SignalSourcesPanel(): JSX.Element {
    const { loadSources, loadSourceConfigs, loadVisionScanners, loadProductDataEvents } = useActions(signalSourcesLogic)

    useEffect(() => {
        loadSources()
        loadSourceConfigs()
        loadVisionScanners()
        loadProductDataEvents()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    return <AgentsRoster />
}
