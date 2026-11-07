import { useValues } from 'kea'
import { Suspense } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'

import type { WorkflowLogicProps } from './workflowLogic'
import type { WorkflowTab } from './workflowSceneLogic'

const WorkflowSandboxSwitchBanner = lazyWithRetry(() =>
    import('./WorkflowSandboxSwitchBanner').then((m) => ({ default: m.WorkflowSandboxSwitchBanner }))
)

export function LazyWorkflowSandboxSwitchBanner({
    isSavedWorkflow,
    activeTab,
    ...props
}: WorkflowLogicProps & { isSavedWorkflow: boolean; activeTab: WorkflowTab }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    // The banner belongs to a saved workflow's builder, not to a template edit or another tab.
    if (
        !featureFlags[FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER] ||
        !isSavedWorkflow ||
        props.editTemplateId ||
        activeTab !== 'workflow'
    ) {
        return null
    }
    return (
        <Suspense fallback={null}>
            <WorkflowSandboxSwitchBanner {...props} />
        </Suspense>
    )
}
