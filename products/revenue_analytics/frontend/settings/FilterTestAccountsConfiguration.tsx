import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

export function FilterTestAccountsConfiguration(): JSX.Element {
    const { filterTestAccounts } = useValues(revenueAnalyticsSettingsLogic)
    const { updateFilterTestAccounts } = useActions(revenueAnalyticsSettingsLogic)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')
    return (
        <SceneSection
            hideTitleAndDescription={!newSceneLayout}
            className={cn(!newSceneLayout && 'gap-y-0')}
            title="Filter test accounts out of revenue analytics"
            description="When enabled, events from test accounts will be excluded from Revenue analytics. You can configure these test accounts here."
        >
            {!newSceneLayout && (
                <>
                    <h3 className="mb-2">Filter test accounts out of revenue analytics</h3>
                    <p className="mb-4">
                        When enabled, events from test accounts will be excluded from Revenue analytics. You can
                        configure these test accounts{' '}
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
