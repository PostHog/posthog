import { BindLogic, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { endpointsEmptyState } from './emptyState/endpointsEmptyState'
import { Endpoints } from './Endpoints'
import { endpointsLogic } from './endpointsLogic'
import { EndpointsUsage } from './EndpointsUsage'
import { endpointsUsageLogic } from './endpointsUsageLogic'
import { InsightPickerEndpointModal } from './InsightPickerEndpointModal'
import { OverlayForNewEndpointMenu } from './newEndpointMenu'

export const scene: SceneExport = {
    component: EndpointsScene,
    logic: endpointsLogic,
    productKey: ProductKey.ENDPOINTS,
    emptyState: endpointsEmptyState,
}

export function EndpointsScene(): JSX.Element {
    const { activeTab } = useValues(endpointsLogic)

    const tabs: LemonTab<string>[] = [
        {
            key: 'endpoints',
            label: 'Endpoints',
            content: <Endpoints />,
            link: urls.endpoints(),
        },
        {
            key: 'usage',
            label: 'Usage',
            content: <EndpointsUsage />,
            link: urls.endpointsUsage(),
        },
    ]
    return (
        <BindLogic logic={endpointsLogic} props={{}}>
            <BindLogic logic={endpointsUsageLogic} props={{}}>
                <SceneContent>
                    <SceneTitleSection
                        name={sceneConfigurations[Scene.EndpointsScene].name}
                        description={sceneConfigurations[Scene.EndpointsScene].description}
                        resourceType={{
                            type: sceneConfigurations[Scene.EndpointsScene].iconType || 'default_icon_type',
                        }}
                        actions={
                            <Shortcut
                                name="EndpointsNew"
                                keybind={[keyBinds.new]}
                                intent="New endpoint"
                                interaction="click"
                                scope={Scene.EndpointsScene}
                            >
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Endpoint}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        type="primary"
                                        to={urls.sqlEditor({ source: 'endpoint' })}
                                        sideAction={{
                                            dropdown: {
                                                placement: 'bottom-end',
                                                className: 'new-endpoint-overlay',
                                                actionable: true,
                                                overlay: <OverlayForNewEndpointMenu />,
                                            },
                                            'data-attr': 'new-endpoint-dropdown',
                                        }}
                                        data-attr="new-endpoint-button"
                                        size="small"
                                        icon={<IconPlusSmall />}
                                    >
                                        New
                                    </LemonButton>
                                </AccessControlAction>
                            </Shortcut>
                        }
                    />
                    <LemonTabs activeKey={activeTab} data-attr="endpoints-tabs" tabs={tabs} sceneInset />
                    <InsightPickerEndpointModal />
                </SceneContent>
            </BindLogic>
        </BindLogic>
    )
}
