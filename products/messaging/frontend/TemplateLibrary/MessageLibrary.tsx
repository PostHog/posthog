import { IconPlusSmall } from '@posthog/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { MessageTemplatesTable } from './MessageTemplatesTable'

export function MessageLibrary(): JSX.Element {
    return (
        <>
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
        </>
    )
}
