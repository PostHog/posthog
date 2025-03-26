import { IconPlusSmall } from '@posthog/icons'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { HogFunctionLogs } from 'scenes/pipeline/hogfunctions/logs/HogFunctionLogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { broadcastsLogic } from './broadcastsLogic'
import { FunctionsTable } from './FunctionsTable'
import { MessagingTabs } from './MessagingTabs'

export function Broadcasts(): JSX.Element {
    const { broadcastId } = useValues(broadcastsLogic)
    return broadcastId ? (
        <div className="flex flex-col gap-4">
            <HogFunctionConfiguration
                id={broadcastId === 'new' ? null : broadcastId}
                templateId={broadcastId === 'new' ? 'template-new-broadcast' : ''}
            />
            <div className="border rounded p-3 deprecated-space-y-2 bg-surface-primary">
                <h2>Broadcast logs</h2>
                <HogFunctionLogs hogFunctionId={broadcastId} />
            </div>
        </div>
    ) : (
        <>
            <MessagingTabs key="tabs" />
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
