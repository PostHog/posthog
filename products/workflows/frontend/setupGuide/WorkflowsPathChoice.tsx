import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { WorkflowDataSuggestions } from './suggestions/WorkflowDataSuggestions'
import { workflowDataSuggestionsLogic } from './suggestions/workflowDataSuggestionsLogic'
import { workflowsSetupGuideLogic } from './workflowsSetupGuideLogic'

/** The first-run choice on the workflows empty state. The choice picks the onboarding a person gets. */
export function WorkflowsPathChoice(): JSX.Element {
    const { cards } = useValues(workflowDataSuggestionsLogic({ surface: 'empty_state' }))

    // The first suggestion card becomes the one primary button once cards show.
    return (
        <div className="flex flex-col gap-4">
            <PathButtons messagingIsPrimary={cards.length === 0} />
            <WorkflowDataSuggestions />
        </div>
    )
}

function PathButtons({ messagingIsPrimary }: { messagingIsPrimary: boolean }): JSX.Element {
    const { choosePath } = useActions(workflowsSetupGuideLogic)

    return (
        <div className="flex flex-wrap gap-2">
            <LemonButton
                type={messagingIsPrimary ? 'primary' : 'secondary'}
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
            <LemonButton type="secondary" onClick={() => choosePath('broadcast')} data-attr="workflows-path-broadcast">
                Send a broadcast
            </LemonButton>
        </div>
    )
}
