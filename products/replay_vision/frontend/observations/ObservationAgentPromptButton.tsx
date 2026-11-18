import { useMemo } from 'react'

import { IconDocument } from '@posthog/icons'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
import posthog from 'lib/posthog-typed'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { buildObservationContext } from './agentPrompts'

export function ObservationAgentPromptButton({
    observation,
    appearance,
}: {
    observation: ReplayObservationApi
    appearance: 'quill' | 'lemon'
}): JSX.Element | null {
    const context = useMemo(() => buildObservationContext(observation), [observation])
    if (!context) {
        return null
    }
    return (
        <AgentPromptButton
            appearance={appearance}
            variant="outline"
            bordered
            label="Send to agent"
            data-attr="vision-observation-agent-prompt"
            actions={[
                {
                    key: 'context',
                    label: 'Observation context',
                    icon: <IconDocument />,
                    buildPrompt: () => context,
                },
            ]}
            onRun={({ actionKey, agentKey }) =>
                posthog.capture('replay_vision_prompt_used', {
                    observation_id: observation.id,
                    scanner_type: observation.scanner_snapshot?.scanner_type ?? null,
                    mode: actionKey,
                    agent: agentKey,
                })
            }
        />
    )
}
