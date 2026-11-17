import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function RunLinkTagHint(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { refreshCurrentTeam } = useActions(teamLogic)
    if (!currentTeam) {
        return null
    }
    const enabled = currentTeam.workflows_config?.email_workflow_run_link_tag_enabled ?? true

    return (
        <span className="text-xs text-secondary" data-attr="workflows-run-link-tag-hint">
            {enabled
                ? 'Tracked links also get ph_workflow_run, which connects each click to the session it starts. '
                : "Tracked links don't get ph_workflow_run, so clicks aren't connected to sessions. "}
            <Link
                to={urls.settings('environment-workflows', 'workflows-email-run-link-tag')}
                target="_blank"
                // The setting changes in another tab, so reload the team when this tab gets focus back.
                onClick={() => window.addEventListener('focus', () => refreshCurrentTeam(), { once: true })}
                data-attr="workflows-run-link-tag-settings-link"
            >
                {enabled ? 'Turn it off in settings' : 'Turn it on in settings'}
            </Link>
        </span>
    )
}
