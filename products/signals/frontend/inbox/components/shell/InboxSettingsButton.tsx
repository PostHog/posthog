import { IconGear } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

/** Opens the inbox settings from the scene header, where the Home pane keeps no Settings row or tab. */
export function InboxSettingsButton(): JSX.Element {
    return (
        <Button
            variant="outline"
            nativeButton={false}
            render={<LinkPrimitive to={urls.inbox('settings')} />}
            data-attr="inbox-settings-button"
        >
            <IconGear />
            Settings
        </Button>
    )
}
