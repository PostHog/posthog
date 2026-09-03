import { LemonBanner } from '@posthog/lemon-ui'

export function MissingReleaseIdBanner(): JSX.Element {
    return (
        <LemonBanner
            type="warning"
            action={{
                to: 'https://posthog.com/docs/error-tracking/upload-source-maps',
                targetBlank: true,
                children: 'Read more',
                'data-attr': 'error-tracking-missing-release-id-docs',
            }}
            className="m-2"
        >
            This exception has no release attached. Your symbol sets were uploaded without one, so the release has to
            come from the SDK. This event did not report it. Update your PostHog SDK package to the latest version.
        </LemonBanner>
    )
}
