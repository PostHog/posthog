import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useChatActionComposer } from '../../ChatActionComposerContext'
import { DataToolRow } from '../DataToolRow'
import { GenericMcpToolRenderer } from '../GenericMcpToolRenderer'
import { asRecord, getToolOutputRecord } from '../getToolOutputRecord'
import type { ToolRendererProps } from '../toolRegistry'

const ACTION_KINDS = ['insert', 'send', 'run'] as const
type SuggestedActionKind = (typeof ACTION_KINDS)[number]

/** One action as the `suggest-actions` tool returns it: final strings only, no template or args. */
export interface SuggestedAction {
    key: string
    label: string
    kind: SuggestedActionKind
    message: string
}

function isSuggestedAction(value: unknown): value is SuggestedAction {
    const record = asRecord(value)
    return (
        !!record &&
        typeof record.key === 'string' &&
        typeof record.label === 'string' &&
        typeof record.message === 'string' &&
        ACTION_KINDS.includes(record.kind as SuggestedActionKind)
    )
}

/** The rendered actions from a completed `suggest-actions` call; null when the payload is not one. */
export function extractSuggestedActions(message: ToolRendererProps['message']): SuggestedAction[] | null {
    const output = getToolOutputRecord(message)
    const actions = output?.actions
    if (!Array.isArray(actions) || !actions.every(isSuggestedAction)) {
        return null
    }
    return actions
}

/**
 * Buttons for the actions the agent offered at the end of its turn. `insert` only fills the
 * composer; `send` and `run` submit the message as the next turn, so they wait for the turn to end
 * and for the composer to be free. The composer comes from the hosting surface through
 * `ChatActionComposerProvider`; a thread rendered without one shows the buttons disabled.
 */
export function SuggestActionsWidget(props: ToolRendererProps): JSX.Element {
    const { message, turnComplete } = props
    const { featureFlags } = useValues(featureFlagLogic)
    const composer = useChatActionComposer()
    const enabled = !!featureFlags[FEATURE_FLAGS.POSTHOG_AI_CHAT_ACTIONS]
    const actions = enabled && message.status === 'completed' ? extractSuggestedActions(message) : null

    if (!actions?.length) {
        return <GenericMcpToolRenderer {...props} />
    }

    const disabledReason = (action: SuggestedAction): string | undefined => {
        if (!composer) {
            return 'Not available in this view'
        }
        if (action.kind === 'insert') {
            return undefined
        }
        if (!turnComplete) {
            return 'Wait for the agent to finish this turn'
        }
        return composer.sendDisabledReason ?? undefined
    }

    return (
        <DataToolRow {...props}>
            <div className="flex flex-wrap gap-2">
                {actions.map((action) => (
                    <LemonButton
                        key={action.key}
                        type="secondary"
                        size="small"
                        data-attr="posthog-ai-suggested-action"
                        data-action-kind={action.kind}
                        disabledReason={disabledReason(action)}
                        onClick={() =>
                            action.kind === 'insert' ? composer?.insert(action.message) : composer?.send(action.message)
                        }
                    >
                        {action.label}
                    </LemonButton>
                ))}
            </div>
        </DataToolRow>
    )
}
