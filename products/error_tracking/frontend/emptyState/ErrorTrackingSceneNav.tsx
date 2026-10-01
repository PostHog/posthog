import { useActions } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import {
    ErrorTrackingSceneActiveTab,
    errorTrackingSceneLogic,
} from '../scenes/ErrorTrackingScene/errorTrackingSceneLogic'

/** The setup screen only covers the issue tabs, so this keeps the Configuration tab one click away. */
export function ErrorTrackingSceneNav(): JSX.Element {
    const { setActiveTab } = useActions(errorTrackingSceneLogic)
    return (
        <LemonTabs<ErrorTrackingSceneActiveTab>
            activeKey="issues"
            onChange={setActiveTab}
            tabs={[
                { key: 'issues', label: 'Issues' },
                { key: 'configuration', label: 'Configuration' },
            ]}
            sceneInset
        />
    )
}
