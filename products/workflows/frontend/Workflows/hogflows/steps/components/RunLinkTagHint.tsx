import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { runLinkTaggingEnabled } from 'products/workflows/frontend/scenes/settings/runLinkTagging'
import { RunLinkTagSettingsLink } from 'products/workflows/frontend/scenes/settings/RunLinkTagSettingsLink'

export function RunLinkTagHint(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

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
