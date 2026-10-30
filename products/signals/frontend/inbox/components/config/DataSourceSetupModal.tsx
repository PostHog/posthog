import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { signalSourcesLogic } from '../../signalSourcesLogic'
import { DataSourceSetup } from './DataSourceSetup'

export function DataSourceSetupModal(): JSX.Element | null {
    const { dataSourceSetupSource, dataSourceSetupOAuthRedirectUrl, externalAgents } = useValues(signalSourcesLogic)
    const { closeDataSourceSetup, onDataSourceSetupComplete } = useActions(signalSourcesLogic)
    if (!dataSourceSetupSource) {
        return null
    }
    const agent = externalAgents.find((item) => item.source === dataSourceSetupSource)

    return (
        <LemonModal
            isOpen
            onClose={closeDataSourceSetup}
            width={760}
            title={`Connect ${agent?.label ?? dataSourceSetupSource}`}
            description={agent?.watches}
        >
            <DataSourceSetup
                source={dataSourceSetupSource}
                onComplete={onDataSourceSetupComplete}
                onCancel={closeDataSourceSetup}
                cancelLabel="Cancel"
                oauthRedirectUrl={dataSourceSetupOAuthRedirectUrl}
            />
        </LemonModal>
    )
}
