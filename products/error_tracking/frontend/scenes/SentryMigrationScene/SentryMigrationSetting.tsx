import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function SentryMigrationSetting(): JSX.Element {
    return (
        <div>
            <LemonButton type="secondary" to={urls.errorTrackingSentryMigration()}>
                Migrate from Sentry
            </LemonButton>
        </div>
    )
}
