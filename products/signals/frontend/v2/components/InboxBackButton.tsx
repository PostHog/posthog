import { IconArrowLeft } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

/** Back button to the inbox: the scene back arrow plus the inbox icon and name, at regular button size. Shared by every v2 detail page. */
export function InboxBackButton({ className }: { className?: string }): JSX.Element {
    return (
        <Link
            to={urls.v2Inbox()}
            aria-label="Go back to Inbox"
            className={cn('flex items-center gap-1.5', className)}
            buttonProps={{ variant: 'default' }}
            tooltip="Go back to Inbox"
            data-attr="v2-back-to-inbox"
        >
            <IconArrowLeft aria-hidden="true" />
            {iconForType('inbox')}
            Inbox
        </Link>
    )
}
