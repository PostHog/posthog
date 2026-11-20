import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

export function FilterTestAccountsConfiguration({
    hideTitle = false,
}: {
    /** Leaves out the heading that the settings page already shows. */
    hideTitle?: boolean
}): JSX.Element {
    const { filterTestAccounts } = useValues(revenueAnalyticsSettingsLogic)
    const { updateFilterTestAccounts } = useActions(revenueAnalyticsSettingsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <SceneSection title={hideTitle ? undefined : 'Filter out internal and test users from revenue analytics'}>
                <Text size="xs" render={<p className="m-0 max-w-160" />}>
                    When enabled, events from test accounts will be excluded from Revenue analytics. You can configure
                    these test accounts{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive to={urls.settings('environment-customization', 'internal-user-filtering')} />
                        }
                    >
                        here
                    </Button>
                    .
                </Text>
                <QuillSettingSwitch
                    label="Filter out internal and test users"
                    checked={filterTestAccounts}
                    onCheckedChange={updateFilterTestAccounts}
                    disabledReason={restrictedReason}
                />
            </SceneSection>
        )
    }

    return (
        <SceneSection
            title={hideTitle ? undefined : 'Filter out internal and test users from revenue analytics'}
            description={
                <>
                    When enabled, events from test accounts will be excluded from Revenue analytics. You can configure
                    these test accounts{' '}
                    <Link to={urls.settings('environment-customization', 'internal-user-filtering')}>here</Link>.
                </>
            }
        >
            <LemonSwitch
                onChange={updateFilterTestAccounts}
                checked={filterTestAccounts}
                label="Filter out internal and test users"
                bordered
                disabledReason={restrictedReason}
            />
        </SceneSection>
    )
}
