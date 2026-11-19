import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { runLinkTaggingEnabled } from 'products/workflows/frontend/scenes/settings/runLinkTagging'
import { RunLinkTagSettingsLink } from 'products/workflows/frontend/scenes/settings/RunLinkTagSettingsLink'

export function RunLinkTagHint(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { refreshCurrentTeam } = useActions(teamLogic)

    // The setting saves in the settings tab the link opens, and the reader can come back before or after
    // saving it there. So once the reader has opened it, reload the team on every return while the hint
    // is on the page. Readers who never open it cost no request.
    const [openedSettings, setOpenedSettings] = useState(false)
    useEffect(() => {
        if (!openedSettings) {
            return
        }
        const onFocus = (): void => {
            refreshCurrentTeam()
        }
        window.addEventListener('focus', onFocus)
        return () => window.removeEventListener('focus', onFocus)
    }, [openedSettings, refreshCurrentTeam])

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
            <RunLinkTagSettingsLink
                dataAttr="workflows-run-link-tag-settings-link"
                onOpen={() => setOpenedSettings(true)}
            >
                {enabled ? 'Turn it off in settings' : 'Turn it on in settings'}
            </RunLinkTagSettingsLink>
        </span>
    )
}
