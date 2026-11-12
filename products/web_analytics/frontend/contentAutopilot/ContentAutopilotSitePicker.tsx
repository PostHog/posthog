import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { contentAutopilotLogic } from './contentAutopilotLogic'

/** Picks the site the Opportunities, Drafts and Settings tabs work on. The prompt tabs cover the whole project. */
export const ContentAutopilotSitePicker = (): JSX.Element | null => {
    const { profile, siteProfiles } = useValues(contentAutopilotLogic)
    const { beginOnboarding, selectProfile } = useActions(contentAutopilotLogic)

    if (!profile) {
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
            <LemonButton size="small" type="secondary" icon={<IconPlusSmall />} onClick={beginOnboarding}>
                Add site
            </LemonButton>
        </div>
    )
}
