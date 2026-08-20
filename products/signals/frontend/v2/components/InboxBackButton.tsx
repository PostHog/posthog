import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'

/** The standard scene back button, pointing at the inbox. Shared by every v2 detail page. */
export function InboxBackButton({ className }: { className?: string }): JSX.Element {
    return (
        <SceneBreadcrumbBackButton
            forceBackTo={{ key: 'v2-inbox', name: 'Inbox', path: urls.v2Inbox() }}
            className={className}
        />
    )
}
