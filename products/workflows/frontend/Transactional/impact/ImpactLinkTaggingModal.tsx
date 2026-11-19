import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { WorkflowsRunLinkTagSettings } from 'products/workflows/frontend/scenes/settings/WorkflowsRunLinkTagSettings'

import { emailImpactLogic } from './emailImpactLogic'

export function ImpactLinkTaggingModal(): JSX.Element {
    const { linkTaggingSettingsOpen } = useValues(emailImpactLogic)
    const { closeLinkTaggingSettings } = useActions(emailImpactLogic)

    return (
        <LemonModal
            isOpen={linkTaggingSettingsOpen}
            onClose={closeLinkTaggingSettings}
            title="Connect email clicks to sessions"
            description="This setting covers every workflow and broadcast email in this project. It connects each tracked click on a link to the domain you send from to the session it starts on your site."
            footer={
                <LemonButton
                    type="secondary"
                    onClick={closeLinkTaggingSettings}
                    data-attr="email-impact-link-tagging-done"
                >
                    Done
                </LemonButton>
            }
            width={520}
        >
            <WorkflowsRunLinkTagSettings />
        </LemonModal>
    )
}
