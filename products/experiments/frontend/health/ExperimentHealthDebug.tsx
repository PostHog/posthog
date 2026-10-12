import { useValues } from 'kea'

import { LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { HealthDebugTables } from './HealthDebugTables'

export function ExperimentHealthDebug(): JSX.Element | null {
    const { superpowersEnabled } = useValues(superpowersLogic)
    const { experiment } = useValues(experimentLogic)

    // Null health means the experiment-health-findings flag is off for this user, so only staff who
    // work on the health layer see this section.
    if (!superpowersEnabled || experiment.health === null) {
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
