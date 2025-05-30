import { IconPlusSmall } from '@posthog/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { MessagingTabs } from '../MessagingTabs'
import { messageLibraryLogic } from './messageLibraryLogic'
import { MessageTemplatesTable } from './MessageTemplatesTable'

export function MessageLibrary(): JSX.Element {
    return (
        <div className="messaging-library">
            <MessagingTabs key="library-tabs" />
            <PageHeader
                caption="Create and manage messages"
                buttons={
                    <LemonButton
                        data-attr="new-message-button"
                        icon={<IconPlusSmall />}
                        size="small"
                        type="primary"
                        to={urls.messagingLibraryTemplateNew()}
                    >
                        New template
                    </LemonButton>
                }
            />

            <MessageTemplatesTable />
        </div>
    )
}

export const scene: SceneExport = {
    component: MessageLibrary,
    logic: messageLibraryLogic,
}
