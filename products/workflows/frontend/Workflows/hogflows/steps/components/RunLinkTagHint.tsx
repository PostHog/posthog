import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function RunLinkTagHint(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam) {
        return null
    }
    const enabled = currentTeam.workflows_config?.email_workflow_run_link_tag_enabled ?? true

    return (
        <span className="text-xs text-secondary" data-attr="workflows-run-link-tag-hint">
            <span>
                {enabled
                    ? 'Tracked clicks on links to the domain you send from are connected to the sessions they start, including session replays when recording is on.'
                    : "Tracked link clicks aren't connected to sessions or session replays."}
            </span>{' '}
            <Link
                to={urls.settings('environment-workflows', 'workflows-email-run-link-tag')}
                target="_blank"
                data-attr="workflows-run-link-tag-settings-link"
            >
                {enabled ? 'Turn it off in settings' : 'Turn it on in settings'}
            </Link>
        </span>
    )
}
