import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { BlastRadiusApi } from 'products/workflows/frontend/generated/api.schemas'

export interface SkippedTestAccountFiltersNoticeProps {
    blastRadius: BlastRadiusApi | null | undefined
}

/** Names the test account filters a batch audience leaves out, since they only apply to events. */
export function SkippedTestAccountFiltersNotice({
    blastRadius,
}: SkippedTestAccountFiltersNoticeProps): JSX.Element | null {
    const skipped = blastRadius?.skipped_test_account_filters ?? []
    if (skipped.length === 0) {
        return null
    }
    return (
        <LemonBanner type="info">
            {skipped.length === 1 ? 'One' : skipped.length}{' '}
            {skipped.length === 1 ? 'test account filter only applies' : 'test account filters only apply'} to events,
            not people, so this audience leaves {skipped.length === 1 ? 'it' : 'them'} out:{' '}
            {skipped.map((key, index) => (
                <span key={key}>
                    {index > 0 && ', '}
                    <code>{key}</code>
                </span>
            ))}
            . Review them in{' '}
            <Link
                to={urls.settings('environment-customization', 'internal-user-filtering')}
                target="_blank"
                data-attr="workflows-skipped-test-account-filters-settings"
            >
                project settings
            </Link>
            .
        </LemonBanner>
    )
}
