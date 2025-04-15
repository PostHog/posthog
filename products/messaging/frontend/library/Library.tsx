import { IconPlusSmall } from '@posthog/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { MessagingTabs } from '../MessagingTabs'
import { libraryLogic } from './libraryLogic'
import { MessagesTable } from './MessagesTable'
import { TemplatesTable } from './TemplatesTable'

export function Library(): JSX.Element {
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

            <TemplatesTable />

            <LemonDivider />

            <MessagesTable />
        </div>
    )
}

export const scene: SceneExport = {
    component: Library,
    logic: libraryLogic,
}
