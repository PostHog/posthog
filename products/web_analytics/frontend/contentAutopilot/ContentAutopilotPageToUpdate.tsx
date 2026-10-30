import { Link } from '@posthog/lemon-ui'

import stringWithWBR from 'lib/utils/stringWithWBR'

import type { ContentAutopilotPageTarget } from './utils'

const breakablePath = (path: string): JSX.Element =>
    path.startsWith('/') && path.length > 1 ? <>/{stringWithWBR(path.slice(1))}</> : stringWithWBR(path)

export const ContentAutopilotPageToUpdate = ({ page }: { page: ContentAutopilotPageTarget | null }): JSX.Element => {
    if (!page) {
        return <span className="text-sm text-muted">Picked when drafting</span>
    }
    if (page.isNewPage) {
        return (
            <span className="text-sm">
                New page <span className="text-muted break-words">{breakablePath(page.path)}</span>
            </span>
        )
    }
    return (
        <span className="text-sm">
            Update{' '}
            <Link to={page.url} target="_blank" className="break-words">
                {breakablePath(page.path)}
            </Link>
        </span>
    )
}
