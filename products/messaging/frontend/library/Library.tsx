import { IconPlusSmall } from '@posthog/icons'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { MessagingTabs } from '../MessagingTabs'
import { libraryLogic } from './libraryLogic'
import { templatesLogic } from './templatesLogic'
import { TemplatesTable } from './TemplatesTable'

// Wrapper component to ensure templatesLogic is unmounted when component unmounts
function TemplatesSection(): JSX.Element {
    // This will mount the logic when component mounts and unmount when component unmounts
    useValues(templatesLogic)
    return <TemplatesTable />
}

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

            <TemplatesSection />
        </div>
    )
}

export const scene: SceneExport = {
    component: Library,
    logic: libraryLogic,
}
