import { useActions } from 'kea'

import { AiFirstCreateScene } from 'scenes/max/aiFirstCreate/AiFirstCreateScene'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { NEW_BROADCAST_SUGGESTIONS } from './broadcastAgentContext'
import { newBroadcastAgentLogic } from './newBroadcastAgentLogic'
import { NEW_BROADCAST_HANDOFF } from './newBroadcastHandoff'

/** The AI-first "New broadcast" screen: the composer first, with the step-by-step wizard behind the escape hatch. */
export function NewBroadcastAgent(): JSX.Element {
    const { openWizardFromAiComposer } = useActions(newBroadcastAgentLogic)

    return (
        <AiFirstCreateScene
            handoff={NEW_BROADCAST_HANDOFF}
            banner="We're trialling writing broadcasts with PostHog AI. Describe what you want to send and to whom, and it drafts the broadcast for you to review before it goes out."
            escapeHatchLabel="Set it up step by step instead"
            onEscapeHatch={openWizardFromAiComposer}
            suggestions={NEW_BROADCAST_SUGGESTIONS}
            suggestionIcon={iconForType('broadcasts')}
            dataAttr="new-broadcast-agent"
        />
    )
}
