import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'

import { FeatureFlagConfig } from '~/types'

import {
    featureFlagConfigFormat,
    featureFlagConfigFormatLabel,
    isRulesV2EditableConfig,
} from './featureFlagConfigFormat'

export function FeatureFlagConfigReadonlyNotice({ filters }: { filters: FeatureFlagConfig }): JSX.Element {
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const label = featureFlagConfigFormatLabel(filters)
    const editable = isRulesV2EditableConfig(filters, featureFlags)
    return (
        <LemonBanner type="info">
            {featureFlagConfigFormat(filters) !== 'v2' ? (
                <>
                    This flag is stored as <strong>{label}</strong>, which this page cannot display or change.
                </>
            ) : editable ? (
                <>
                    This flag is stored as <strong>{label}</strong> and is shown read-only here. Open the flag page to
                    change its rules; archiving is not available yet.
                </>
            ) : (
                <>
                    This flag is stored as <strong>{label}</strong> and is shown read-only here. You can enable and
                    disable it; archiving and editing its rules are not available yet.
                </>
            )}
        </LemonBanner>
    )
}
