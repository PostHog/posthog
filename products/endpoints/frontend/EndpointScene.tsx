import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPause, IconPlay, IconTrash } from '@posthog/icons'
import { LemonDialog, LemonDivider } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import 'lib/lemon-ui/LemonModal/LemonModal'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ActivityScope } from '~/types'

import { EndpointSceneHeader } from './EndpointHeader'
import { EndpointConfiguration } from './endpoint-tabs/EndpointConfiguration'
import { EndpointOverview } from './endpoint-tabs/EndpointOverview'
import { EndpointPlayground } from './endpoint-tabs/EndpointPlayground'
import { EndpointQuery } from './endpoint-tabs/EndpointQuery'
import { endpointLogic } from './endpointLogic'
import { EndpointTab, endpointSceneLogic } from './endpointSceneLogic'

interface EndpointProps {
    tabId?: string
}

export const scene: SceneExport = {
    component: EndpointScene,
    logic: endpointSceneLogic,
}

export function EndpointScene({ tabId }: EndpointProps = {}): JSX.Element {
    if (!tabId) {
        throw new Error('<EndpointScene /> must receive a tabId prop')
    }
    const { endpoint, endpointLoading, activeTab } = useValues(endpointSceneLogic({ tabId }))
    const { deleteEndpoint, confirmToggleActive } = useActions(endpointLogic({ tabId }))
    const { searchParams } = useValues(router)

    const tabs: LemonTab<EndpointTab>[] = [
        {
            key: EndpointTab.QUERY,
            label: 'Query',
            content: <EndpointQuery tabId={tabId} />,
            link: endpoint
                ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.QUERY }).url
                : undefined,
        },
        {
            key: EndpointTab.CONFIGURATION,
            label: 'Configuration',
            content: <EndpointConfiguration tabId={tabId} />,
            link: endpoint
                ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.CONFIGURATION }).url
                : undefined,
        },
        {
            key: EndpointTab.PLAYGROUND,
            label: 'Playground',
            content: <EndpointPlayground tabId={tabId} />,
            link: endpoint
                ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.PLAYGROUND }).url
                : undefined,
        },
        {
            key: EndpointTab.HISTORY,
            label: 'History',
            content: endpoint ? <ActivityLog scope={ActivityScope.ENDPOINT} id={endpoint.id} /> : <></>,
            link: endpoint
                ? combineUrl(urls.endpoint(endpoint.name), { ...searchParams, tab: EndpointTab.HISTORY }).url
                : undefined,
        },
    ]

    const handleDelete = (): void => {
        if (!endpoint?.name) {
            return
        }

        LemonDialog.open({
            title: 'Delete endpoint?',
            content: (
                <div className="text-sm text-secondary">
                    Are you sure you want to delete this endpoint? This action cannot be undone.
                </div>
            ),
            primaryButton: {
                children: 'Delete',
                type: 'primary',
                status: 'danger',
                onClick: () => {
                    deleteEndpoint(endpoint.name)
                    router.actions.push(urls.endpoints())
                },
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    const handleToggleActive = (): void => {
        if (!endpoint) {
            return
        }
        confirmToggleActive(endpoint)
    }

    return (
        <BindLogic logic={endpointSceneLogic} props={{ tabId }}>
            <SceneContent className="Endpoint">
                <EndpointSceneHeader tabId={tabId} />
                {!endpointLoading && <EndpointOverview tabId={tabId} />}
                <LemonTabs activeKey={activeTab} tabs={tabs} />
            </SceneContent>
            {endpoint && (
                <ScenePanel>
                    <ScenePanelActionsSection>
                        <ButtonPrimitive menuItem onClick={handleToggleActive}>
                            {endpoint.is_active ? <IconPause /> : <IconPlay />}
                            {endpoint.is_active ? 'Deactivate' : 'Activate'}
                        </ButtonPrimitive>
                        <LemonDivider />
                        <ButtonPrimitive menuItem onClick={handleDelete} className="text-danger">
                            <IconTrash />
                            Delete endpoint
                        </ButtonPrimitive>
                    </ScenePanelActionsSection>
                </ScenePanel>
            )}
        </BindLogic>
    )
}
