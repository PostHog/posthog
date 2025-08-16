import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'
import { SceneSection } from '~/layout/scenes/SceneContent'
import { cn } from 'lib/utils/css-classes'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function FilterTestAccountsConfiguration(): JSX.Element {
    const { filterTestAccounts } = useValues(revenueAnalyticsSettingsLogic)
    const { updateFilterTestAccounts } = useActions(revenueAnalyticsSettingsLogic)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')
    return (
        <SceneSection
            hideTitleAndDescription={!newSceneLayout}
            className={cn(!newSceneLayout && 'gap-y-0')}
            title="Filter test accounts out of revenue analytics"
            description="When enabled, events from test accounts will be excluded from Revenue analytics. You can configure these tests account here."
        >
            {!newSceneLayout && (
                <>
                    <h3 className="mb-2">Filter test accounts out of revenue analytics</h3>
                    <p className="mb-4">
                        When enabled, events from test accounts will be excluded from Revenue analytics. You can
                        configure these tests account{' '}
                        <Link to={urls.settings('project-product-analytics', 'internal-user-filtering')}>here</Link>.
                    </p>
                </>
            )}
            <LemonSwitch
                onChange={updateFilterTestAccounts}
                checked={filterTestAccounts}
                label="Filter test accounts out of revenue analytics"
                bordered
            />
        </SceneSection>
    )
}
