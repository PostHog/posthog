import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { WorkflowDataSuggestions } from './suggestions/WorkflowDataSuggestions'
import { workflowsSetupGuideLogic } from './workflowsSetupGuideLogic'

/** The first-run choice on the workflows empty state. The choice picks the onboarding a person gets. */
export function WorkflowsPathChoice(): JSX.Element {
    const { choosePath } = useActions(workflowsSetupGuideLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    onClick={() => choosePath('messaging')}
                    data-attr="workflows-path-messaging"
                >
                    Message your users
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={() => choosePath('automation')}
                    data-attr="workflows-path-automation"
                >
                    Automate a process
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={() => choosePath('broadcast')}
                    data-attr="workflows-path-broadcast"
                >
                    Send a broadcast
                </LemonButton>
            </div>
            {featureFlags[FEATURE_FLAGS.WORKFLOWS_DATA_SUGGESTIONS] && <WorkflowDataSuggestions />}
        </div>
    )
}
