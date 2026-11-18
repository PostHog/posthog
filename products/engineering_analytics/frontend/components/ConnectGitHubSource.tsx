import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

/**
 * The scene-level empty state covers a project that never connected a GitHub source. This covers a
 * source removed while the scene is open, so the tab says what to do instead of showing a failed load.
 */
export function ConnectGitHubSource(): JSX.Element {
    return (
        <LemonBanner
            type="info"
            action={{
                children: 'Connect GitHub source',
                to: urls.dataWarehouseSourceNew('Github'),
                'data-attr': 'engineering-analytics-connect-github',
            }}
        >
            No GitHub source is connected. Connect one to see pull requests and workflow runs here.
        </LemonBanner>
    )
}
