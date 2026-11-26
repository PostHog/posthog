import { useActions, useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { contentAutopilotLogic } from './contentAutopilotLogic'

/** Picks the site the Opportunities, Drafts and Settings tabs work on. The prompt tabs cover the whole project. */
export const ContentAutopilotSitePicker = (): JSX.Element | null => {
    const { profile, siteProfiles } = useValues(contentAutopilotLogic)
    const { selectProfile } = useActions(contentAutopilotLogic)

    // A project tracks one site. Projects that added more before that keep a picker to reach and delete them.
    if (!profile || siteProfiles.length < 2) {
        return null
    }
    const options = siteProfiles.map((siteProfile) => ({
        value: siteProfile.id,
        label: siteProfile.name || siteProfile.domain,
    }))
    return (
        <div className="flex flex-wrap items-center gap-2" data-attr="content-autopilot-site-picker">
            <Select<string> value={profile.id} onValueChange={(id) => id && selectProfile(id)}>
                <SelectTrigger aria-label="Site">
                    <SelectValue>
                        {(id: string | null) => options.find((option) => option.value === id)?.label}
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    {options.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}
