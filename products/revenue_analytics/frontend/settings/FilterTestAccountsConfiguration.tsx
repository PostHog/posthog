import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

export function FilterTestAccountsConfiguration(): JSX.Element {
    const { filterTestAccounts } = useValues(revenueAnalyticsSettingsLogic)
    const { updateFilterTestAccounts } = useActions(revenueAnalyticsSettingsLogic)
    return (
        <SceneSection
            title="Filter test accounts out of revenue analytics"
            description="When enabled, events from test accounts will be excluded from Revenue analytics. You can configure these test accounts here."
        >
            <LemonSwitch
                onChange={updateFilterTestAccounts}
                checked={filterTestAccounts}
                label="Filter test accounts out of revenue analytics"
                bordered
            />
        </SceneSection>
    )
}
