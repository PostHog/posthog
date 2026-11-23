import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function RunLinkTagHint(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { refreshCurrentTeam } = useActions(teamLogic)
    const projectOff = !!currentTeam && currentTeam.workflows_config?.email_workflow_run_link_tag_enabled === false

    useEffect(() => {
        if (!projectOff) {
            return
        }
        // The link opens settings in a new tab, so a broadcast edit waiting on autosave survives. Reload the
        // project on return so the switch it disables follows the setting turned on there.
        const reload = (): void => refreshCurrentTeam()
        window.addEventListener('focus', reload)
        return () => window.removeEventListener('focus', reload)
    }, [projectOff, refreshCurrentTeam])

    if (!projectOff) {
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
