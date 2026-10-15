import { useValues } from 'kea'

import { LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { HealthDebugTables } from './HealthDebugTables'

export function ExperimentHealthDebug(): JSX.Element | null {
    const { superpowersEnabled } = useValues(superpowersLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!superpowersEnabled || !featureFlags[FEATURE_FLAGS.EXPERIMENT_HEALTH_FINDINGS]) {
        return null
    }

    return (
        <LemonCollapse
            panels={[
                {
                    key: 'health-debug',
                    header: (
                        <span className="flex items-center gap-2">
                            Health checks debug
                            <LemonTag type="muted">Staff only</LemonTag>
                        </span>
                    ),
                    dataAttr: 'experiment-health-debug',
                    content: <HealthDebugTables />,
                },
            ]}
        />
    )
}
