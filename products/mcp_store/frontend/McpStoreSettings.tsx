import { useActions, useValues } from 'kea'
import { useCallback, useEffect } from 'react'

import { mcpStoreLogic } from './mcpStoreLogic'
import { AddCustomServerForm } from './scene/AddCustomServerForm'
import { MarketplaceBrowser } from './scene/MarketplaceBrowser'
import { ServerDetailPanel } from './scene/ServerDetailPanel'

export function McpStoreSettings(): JSX.Element {
    const { sceneView, selectedInstallation, selectedTemplate } = useValues(mcpStoreLogic)
    const { loadInstallations, loadServers } = useActions(mcpStoreLogic)

    // Refresh on tab focus — an OAuth redirect can complete in another tab
    // and we want the state to catch up.
    const refresh = useCallback(() => {
        loadInstallations()
        loadServers()
    }, [loadInstallations, loadServers])

    useEffect(() => {
        const onVisible = (): void => {
            if (document.visibilityState === 'visible') {
                refresh()
            }
        }
        window.addEventListener('focus', refresh)
        document.addEventListener('visibilitychange', onVisible)
        return () => {
            window.removeEventListener('focus', refresh)
            document.removeEventListener('visibilitychange', onVisible)
        }
    }, [refresh])

    return (
        <>
            {sceneView === 'detail' ? (
                <ServerDetailPanel installation={selectedInstallation} template={selectedTemplate} />
            ) : (
                <MarketplaceBrowser />
            )}
            <AddCustomServerForm />
        </>
    )
}
