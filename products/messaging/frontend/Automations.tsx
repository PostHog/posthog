import { IconPlusSmall } from '@posthog/icons'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { automationsLogic } from './automationsLogic'
import { FunctionsTable } from './FunctionsTable'
import { MessagingTabs } from './MessagingTabs'

export function Automations(): JSX.Element {
    const { automationId } = useValues(automationsLogic)
    return automationId ? (
        <HogFunctionConfiguration
            id={automationId === 'new' ? null : automationId}
            templateId={automationId === 'new' ? 'template-new-automation' : ''}
        />
    ) : (
        <>
            <MessagingTabs key="tabs" />
            <PageHeader
                caption="Create automated messaging workflows for your users"
                buttons={
                    <LemonButton
                        data-attr="new-automation"
                        to={urls.messagingAutomationNew()}
                        type="primary"
                        icon={<IconPlusSmall />}
                    >
                        New automation
                    </LemonButton>
                }
            />
            <FunctionsTable type="automation" />
        </>
    )
}

export const scene: SceneExport = {
    component: Automations,
    logic: automationsLogic,
}
