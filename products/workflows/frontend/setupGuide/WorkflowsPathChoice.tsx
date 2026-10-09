import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { workflowsSetupGuideLogic } from './workflowsSetupGuideLogic'

/** The first-run choice on the workflows empty state. The choice picks the onboarding a person gets. */
export function WorkflowsPathChoice(): JSX.Element {
    const { choosePath } = useActions(workflowsSetupGuideLogic)

    return (
        <div className="flex flex-wrap gap-2">
            <LemonButton type="primary" onClick={() => choosePath('messaging')} data-attr="workflows-path-messaging">
                Message your users
            </LemonButton>
            <LemonButton
                type="secondary"
                onClick={() => choosePath('automation')}
                data-attr="workflows-path-automation"
            >
                Automate a process
            </LemonButton>
        </div>
    )
}
