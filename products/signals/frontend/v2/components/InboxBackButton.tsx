import { IconArrowLeft } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

/** The standard scene back button, labeled with the inbox icon and name. Shared by every v2 detail page. */
export function InboxBackButton(): JSX.Element {
    return (
        <Link
            to={urls.v2Inbox()}
            aria-label="Go back to Inbox"
            className="flex w-fit items-center gap-1.5 text-xs text-tertiary"
            buttonProps={{ variant: 'default' }}
            tooltip="Go back to Inbox"
            data-attr="v2-back-to-inbox"
        >
            <IconArrowLeft aria-hidden="true" className="size-3 text-tertiary" />
            <span className="flex items-center text-sm">{iconForType('inbox')}</span>
            Inbox
        </Link>
    )
}
