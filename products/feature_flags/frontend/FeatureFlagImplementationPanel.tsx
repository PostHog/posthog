import { LemonCollapse } from '@posthog/lemon-ui'

import { FeatureFlagInstructions } from 'scenes/feature-flags/FeatureFlagInstructions'

import { FeatureFlagType } from '~/types'

import { isRulesV2FeatureFlagConfig, isV1FeatureFlagConfig } from './featureFlagConfigFormat'

export function FeatureFlagImplementationPanel({
    featureFlag,
    defaultOpen = false,
}: {
    featureFlag: FeatureFlagType
    defaultOpen?: boolean
}): JSX.Element | null {
    // The snippets only cover flags that return a boolean or v1 variants
    const canShowInstructions =
        isV1FeatureFlagConfig(featureFlag.filters) ||
        (isRulesV2FeatureFlagConfig(featureFlag.filters) && featureFlag.filters.return_type === 'boolean')

    if (!canShowInstructions) {
        return null
    }

    return (
        <LemonCollapse
            className="bg-bg-light"
            defaultActiveKey={defaultOpen ? 'implementation' : undefined}
            panels={[
                {
                    key: 'implementation',
                    header: 'How to implement',
                    content: (
                        <div className="flex flex-col gap-4">
                            <p className="text-sm text-muted m-0">
                                Use the following code to implement this feature flag.
                            </p>
                            <FeatureFlagInstructions featureFlag={featureFlag} />
                        </div>
                    ),
                },
            ]}
        />
    )
}
