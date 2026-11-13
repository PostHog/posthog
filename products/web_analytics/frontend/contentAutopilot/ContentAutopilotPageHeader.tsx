import { IconChevronRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

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
}): JSX.Element => (
    <div className="flex flex-col gap-1" data-attr="content-autopilot-page-header">
        <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm">
            <Link
                to={urls.webAnalyticsContentAutopilot()}
                subtle
                onClick={(event) => {
                    if (!event.shiftKey && !event.metaKey && !event.ctrlKey) {
                        event.preventDefault()
                        onBack()
                    }
                }}
                data-attr={backDataAttr}
            >
                {backLabel}
            </Link>
            <IconChevronRight className="shrink-0 text-secondary" />
        </nav>
        <div className="flex flex-wrap items-start justify-between gap-2">
            <h2 className="m-0 min-w-0 flex-1 basis-96 text-lg font-semibold" aria-current="page">
                {title}
            </h2>
            {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
    </div>
)
