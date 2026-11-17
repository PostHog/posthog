import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { contentAutopilotLogic } from './contentAutopilotLogic'

/** Picks the site the Opportunities, Drafts and Settings tabs work on. The prompt tabs cover the whole project. */
export const ContentAutopilotSitePicker = (): JSX.Element | null => {
    const { profile, siteProfiles } = useValues(contentAutopilotLogic)
    const { selectProfile } = useActions(contentAutopilotLogic)

    // A project tracks one site. Projects that added more before that keep a picker to reach and delete them.
    if (!profile || siteProfiles.length < 2) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-2" data-attr="content-autopilot-site-picker">
            <LemonSelect
                size="small"
                aria-label="Site"
                value={profile.id}
                onChange={selectProfile}
                options={siteProfiles.map((siteProfile) => ({
                    value: siteProfile.id,
                    label: siteProfile.name || siteProfile.domain,
                }))}
            />
        </div>
    )
}
