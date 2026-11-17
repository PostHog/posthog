import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function RunLinkTagHint(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { refreshCurrentTeam } = useActions(teamLogic)
    const pendingRefresh = useRef<(() => void) | null>(null)

    useEffect(
        () => () => {
            if (pendingRefresh.current) {
                window.removeEventListener('focus', pendingRefresh.current)
            }
        },
        []
    )

    if (!currentTeam) {
        return null
    }
    // The setting changes in another tab, so reload the team once when this tab gets focus back.
    const refreshOnReturn = (): void => {
        if (pendingRefresh.current) {
            return
        }
        const onFocus = (): void => {
            pendingRefresh.current = null
            refreshCurrentTeam()
        }
        pendingRefresh.current = onFocus
        window.addEventListener('focus', onFocus, { once: true })
    }
    const enabled = currentTeam.workflows_config?.email_workflow_run_link_tag_enabled ?? true

    return (
        <span className="text-xs text-secondary" data-attr="workflows-run-link-tag-hint">
            <span>
                {enabled
                    ? 'Tracked link clicks are connected to the sessions they start, including session replays when recording is on.'
                    : "Tracked link clicks aren't connected to sessions or session replays."}
            </span>{' '}
            <Link
                to={urls.settings('environment-workflows', 'workflows-email-run-link-tag')}
                target="_blank"
                // Capture also sees Cmd/Ctrl-clicks, and middle-clicks only fire auxclick.
                onClickCapture={refreshOnReturn}
                onAuxClick={refreshOnReturn}
                data-attr="workflows-run-link-tag-settings-link"
            >
                {enabled ? 'Turn it off in settings' : 'Turn it on in settings'}
            </Link>
        </span>
    )
}
