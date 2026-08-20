import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'

/** The standard scene back button (the same one dashboards use), pointed at the inbox. Shared by every v2 detail page. */
export function InboxBackButton({ className }: { className?: string }): JSX.Element {
    return (
        <SceneBreadcrumbBackButton
            forceBackTo={{ key: 'V2Inbox', name: 'Inbox', path: urls.v2Inbox() }}
            className={className}
        />
    )
}
