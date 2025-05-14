import { IconPlusSmall } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { HogFunctionConfiguration } from 'scenes/hog-functions/configuration/HogFunctionConfiguration'
import { HogFunctionLogs } from 'scenes/hog-functions/logs/HogFunctionLogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { broadcastsLogic } from './broadcastsLogic'
import { BroadcastTab, broadcastTabsLogic } from './broadcastTabsLogic'
import { FunctionsTable } from './FunctionsTable'
import { MessagingTabs } from './MessagingTabs'

const Broadcast = ({ broadcastId }: { broadcastId: string }): JSX.Element => {
    const { currentTab } = useValues(broadcastTabsLogic)
    const { setTab } = useActions(broadcastTabsLogic)

    const tabs = [
        { key: 'configuration', label: 'Configuration' },
        { key: 'logs', label: 'Logs' },
    ]

    return (
        <div className="flex flex-col">
            {broadcastId !== 'new' && (
                <LemonTabs activeKey={currentTab} onChange={(tab) => setTab(tab as BroadcastTab)} tabs={tabs} />
            )}

            {currentTab === 'configuration' && (
                <HogFunctionConfiguration
                    id={broadcastId === 'new' ? null : broadcastId}
                    templateId={broadcastId === 'new' ? 'template-new-broadcast' : ''}
                    displayOptions={{
                        showStatus: false,
                        showEnabled: false,
                        canEditSource: false,
                    }}
                />
            )}
            {currentTab === 'logs' && <HogFunctionLogs hogFunctionId={broadcastId} />}
        </div>
    )
}

export function Broadcasts(): JSX.Element {
    const { broadcastId } = useValues(broadcastsLogic)

    return broadcastId ? (
        <Broadcast broadcastId={broadcastId} />
    ) : (
        <>
            <MessagingTabs key="broadcasts-tabs" />
            <PageHeader
                caption="Send one time communications to your users"
                buttons={
                    <LemonButton
                        data-attr="new-broadcast"
                        to={urls.messagingBroadcastNew()}
                        type="primary"
                        icon={<IconPlusSmall />}
                    >
                        New broadcast
                    </LemonButton>
                }
            />
            <FunctionsTable type="broadcast" />
        </>
    )
}

export const scene: SceneExport = {
    component: Broadcasts,
    logic: broadcastsLogic,
}
