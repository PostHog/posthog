import { LemonBanner } from '@posthog/lemon-ui'

import { FeatureFlagConfig } from '~/types'

import { featureFlagConfigFormat, featureFlagConfigFormatLabel } from './featureFlagConfigFormat'

export function FeatureFlagConfigReadonlyNotice({ filters }: { filters: FeatureFlagConfig }): JSX.Element {
    const label = featureFlagConfigFormatLabel(filters)
    return (
        <LemonBanner type="info">
            {featureFlagConfigFormat(filters) === 'v2' ? (
                <>
                    This flag is stored as <strong>{label}</strong> and is shown read-only here. You can enable and
                    disable it; archiving and editing its rules are not available yet.
                </>
            ) : (
                <>
                    This flag is stored as <strong>{label}</strong>, which this page cannot display or change.
                </>
            )}
        </LemonBanner>
    )
}
