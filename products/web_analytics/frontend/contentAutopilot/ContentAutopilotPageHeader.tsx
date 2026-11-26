import { IconChevronRight } from '@posthog/icons'
import { Button, Heading } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

/** A page inside AI visibility: a breadcrumb back to the tab it came from, its title, and its actions. */
export const ContentAutopilotPageHeader = ({
    title,
    backLabel,
    backDataAttr,
    onBack,
    actions,
}: {
    title: string
    backLabel: string
    backDataAttr: string
    onBack: () => void
    actions?: React.ReactNode
}): JSX.Element => {
    // A plain click goes back in place, and a modified click still opens the tab in a new window.
    const onBackClick = (event: React.MouseEvent): void => {
        if (!event.shiftKey && !event.metaKey && !event.ctrlKey) {
            event.preventDefault()
            onBack()
        }
    }

    return (
        <div className="flex flex-col gap-1" data-attr="content-autopilot-page-header">
            <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm">
                <Button
                    variant="link-muted"
                    size="inline"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.webAnalyticsContentAutopilot()} onClick={onBackClick} />}
                    data-attr={backDataAttr}
                >
                    {backLabel}
                </Button>
                <IconChevronRight className="shrink-0 text-muted-foreground" />
            </nav>
            <div className="flex flex-wrap items-start justify-between gap-2">
                <Heading size="lg" render={<h2 className="m-0 min-w-0 flex-1 basis-96" aria-current="page" />}>
                    {title}
                </Heading>
                {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
            </div>
        </div>
    )
}
