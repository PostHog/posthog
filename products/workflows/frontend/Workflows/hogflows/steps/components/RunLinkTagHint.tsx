import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function RunLinkTagHint(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam || (currentTeam.workflows_config?.email_workflow_run_link_tag_enabled ?? true)) {
        return null
    }

    return (
        <span className="text-xs text-secondary" data-attr="workflows-run-link-tag-hint">
            <span>Tracked link clicks aren't connected to sessions or session replays in this project.</span>{' '}
            <Link
                to={urls.settings('environment-workflows', 'workflows-email-run-link-tag')}
                target="_blank"
                data-attr="workflows-run-link-tag-settings-link"
            >
                Turn it on in settings
            </Link>
        </span>
    )
}
