import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { runLinkTaggingEnabled } from 'products/workflows/frontend/scenes/settings/runLinkTagging'
import { RunLinkTagSettingsLink } from 'products/workflows/frontend/scenes/settings/RunLinkTagSettingsLink'

export function RunLinkTagHint(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { refreshCurrentTeam } = useActions(teamLogic)

    // The setting changes in the settings tab the link opens, and the reader can come back before or
    // after saving it there, so reload the team on every return while the hint is on the page.
    useEffect(() => {
        const onFocus = (): void => {
            refreshCurrentTeam()
        }
        window.addEventListener('focus', onFocus)
        return () => window.removeEventListener('focus', onFocus)
    }, [refreshCurrentTeam])

    if (!currentTeam) {
        return null
    }
    const enabled = runLinkTaggingEnabled(currentTeam)

    return (
        <span className="text-xs text-secondary" data-attr="workflows-run-link-tag-hint">
            <span>
                {enabled
                    ? 'Tracked clicks on links to the domain you send from are connected to the sessions they start, including session replays when recording is on.'
                    : "Tracked link clicks aren't connected to sessions or session replays."}
            </span>{' '}
            <RunLinkTagSettingsLink dataAttr="workflows-run-link-tag-settings-link">
                {enabled ? 'Turn it off in settings' : 'Turn it on in settings'}
            </RunLinkTagSettingsLink>
        </span>
    )
}
