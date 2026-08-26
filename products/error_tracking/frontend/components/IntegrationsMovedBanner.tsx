import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function IntegrationsMovedBanner(): JSX.Element {
    return (
        <LemonBanner
            type="info"
            className="mb-2"
            action={{
                children: 'Go to project settings',
                to: urls.settings('environment-error-tracking', 'error-tracking-integrations'),
            }}
        >
            <p>
                <strong>Looking for integrations?</strong> Integrations for connecting error tracking with external
                services like GitHub or Linear have moved to project settings.
            </p>
        </LemonBanner>
    )
}
