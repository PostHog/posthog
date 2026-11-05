import { useValues } from 'kea'
import { Suspense } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'

import type { WorkflowLogicProps } from './workflowLogic'

const WorkflowSandboxSwitchBanner = lazyWithRetry(() =>
    import('./WorkflowSandboxSwitchBanner').then((m) => ({ default: m.WorkflowSandboxSwitchBanner }))
)

export function LazyWorkflowSandboxSwitchBanner(props: WorkflowLogicProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]) {
        return null
    }
    return (
        <Suspense fallback={null}>
            <WorkflowSandboxSwitchBanner {...props} />
        </Suspense>
    )
}
