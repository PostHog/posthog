import { BindLogic, useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { useToolStreamListener } from 'products/posthog_ai/frontend/api/logics'
import { resolveToolCall } from 'products/posthog_ai/frontend/api/tools'

import { BROADCAST_AGENT_HEADLINES, buildBroadcastAgentContext } from './broadcastAgentContext'
import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { BroadcastSummary } from './BroadcastSummary'
import { broadcastTestSendLogic } from './broadcastTestSendLogic'
import { BroadcastWizard } from './BroadcastWizard'
import { BroadcastWizardLogicProps, broadcastWizardLogic } from './broadcastWizardLogic'

export const scene: SceneExport<BroadcastWizardLogicProps> = {
    component: BroadcastScene,
    logic: broadcastWizardLogic,
    paramsToProps: ({ params: { id } }): BroadcastWizardLogicProps => ({ id: id || 'new' }),
    productKey: ProductKey.WORKFLOWS,
}

export function BroadcastScene({ id }: BroadcastWizardLogicProps): JSX.Element {
    const logicProps: BroadcastWizardLogicProps = { id: id || 'new' }

    return (
        <BindLogic logic={broadcastWizardLogic} props={logicProps}>
            <BindLogic logic={broadcastPreviewLogic} props={logicProps}>
                <BindLogic logic={broadcastTestSendLogic} props={logicProps}>
                    <BroadcastSceneContent id={logicProps.id} />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function BroadcastSceneContent({ id }: BroadcastWizardLogicProps): JSX.Element {
    const { broadcast, broadcastLoading, broadcastId, name, email, isReadOnly } = useValues(broadcastWizardLogic)
    const { refreshFromAgentEdit } = useActions(broadcastWizardLogic)
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)

    // Debounced so per-keystroke edits don't re-serialize the email into the agent context. The id
    // rides along with the email as one value so a navigation between broadcasts can never pair one
    // broadcast's ref with the other's editor state during the debounce window.
    const debouncedAgentSource = useDebouncedValue(
        useMemo(() => ({ broadcastId, name, email }), [broadcastId, name, email]),
        500
    )
    const agentContextItems = useMemo(
        () =>
            sceneIntegrationEnabled
                ? buildBroadcastAgentContext(
                      debouncedAgentSource.broadcastId,
                      debouncedAgentSource.name,
                      debouncedAgentSource.email
                  )
                : null,
        [sceneIntegrationEnabled, debouncedAgentSource]
    )
    useSceneAgentPanel({
        sceneKey: 'broadcast',
        contextItems: agentContextItems,
        // Only while the wizard is editable: the sent/scheduled summary view has nothing to patch.
        active: !isReadOnly && (id === 'new' || !!broadcast),
        headlines: BROADCAST_AGENT_HEADLINES,
    })
    // An approved email patch mutates the flow server-side while the wizard keeps pre-patch state,
    // so refetch and re-hydrate the email on completion. The refetch is idempotent, so absorbing an
    // event whose target we can't parse is harmless.
    useToolStreamListener({
        tools: ['workflows-patch-action-email', 'workflows-patch-graph', 'workflows-update'],
        onEvent: (event) => {
            if (event.phase !== 'completed' || !broadcastId) {
                return
            }
            const innerInput = resolveToolCall(event.invocation).innerInput
            const targetId = typeof innerInput?.id === 'string' ? innerInput.id : null
            if (targetId && targetId !== broadcastId) {
                return
            }
            refreshFromAgentEdit()
        },
    })

    if (id !== 'new') {
        if (!broadcast && broadcastLoading) {
            return <SpinnerOverlay sceneLevel />
        }
        if (!broadcast) {
            return <NotFound object="broadcast" />
        }
        // Any workflow id resolves on this route, and the wizard would rewrite whatever graph it
        // opened into a broadcast's trigger/email/exit on the next save. Only open real broadcasts.
        if (broadcast.kind !== 'broadcast') {
            return <NotFound object="broadcast" />
        }
        if (broadcast.status !== 'draft') {
            return <BroadcastSummary />
        }
    }

    return <BroadcastWizard />
}
