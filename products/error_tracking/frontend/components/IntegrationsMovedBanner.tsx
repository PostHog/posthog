import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function IntegrationsMovedBanner(): JSX.Element {
    return (
        <LemonBanner type="info" className="mb-2">
            <p>
                <strong>Looking for integrations?</strong> Integrations for connecting error tracking with external
                services like GitHub or Linear have moved to{' '}
                <Link to={urls.settings('environment-error-tracking', 'error-tracking-integrations')}>
                    Project settings &rarr; Error tracking
                </Link>
                .
            </p>
        </LemonBanner>
    )
}
