import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { Skeleton } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import type { FeatureFlagRequestListField } from './featureFlagRequestListField'
import { featureFlagRequestListsLogic } from './featureFlagRequestListsLogic'
import { QuillFeatureFlagRequestLists } from './QuillFeatureFlagRequestLists'

export function FeatureFlagRequestLists({ lists }: { lists: FeatureFlagRequestListField[] }): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(featureFlagRequestListsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!currentTeam) {
        return todayRailNav ? <Skeleton className="h-8 max-w-160" /> : <LemonSkeleton />
    }

    if (todayRailNav) {
        return (
            <QuillFeatureFlagRequestLists
                lists={lists}
                disabled={currentTeamLoading}
                // Chip removal only honors the disabled reason, and a removal during a save would send the old list.
                disabledReason={restrictedReason ?? (currentTeamLoading ? 'Loading…' : null)}
            />
        )
    }

    return (
        <div className="flex flex-col gap-4 max-w-160">
            {lists.map(({ id, label, help, placeholder, dataAttr, value, onChange }) => (
                <LemonField.Pure key={id} label={label} htmlFor={id} help={help}>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={value}
                        onChange={onChange}
                        placeholder={placeholder}
                        id={id}
                        data-attr={dataAttr}
                        loading={currentTeamLoading}
                        disabled={currentTeamLoading}
                        disabledReason={restrictedReason}
                    />
                </LemonField.Pure>
            ))}
        </div>
    )
}
