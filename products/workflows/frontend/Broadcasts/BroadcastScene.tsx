import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { AI_FIRST_COMPOSER_OVERRIDE } from 'scenes/max/aiFirstCreate/aiFirstMode'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { NEW_BROADCAST_AGENT_HEADLINES, buildNewBroadcastComposerContext } from './broadcastAgentContext'
import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { canEditInWizard, isBroadcastShaped } from './broadcastsLogic'
import { BroadcastSummary } from './BroadcastSummary'
import { broadcastTestSendLogic } from './broadcastTestSendLogic'
import { BroadcastWizard } from './BroadcastWizard'
import { BroadcastWizardLogicProps, broadcastWizardLogic } from './broadcastWizardLogic'
import { NewBroadcastAgent } from './NewBroadcastAgent'
import { newBroadcastAgentLogic } from './newBroadcastAgentLogic'

const NEW_BROADCAST_COMPOSER_CONTEXT = buildNewBroadcastComposerContext()

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
    const { broadcast, broadcastLoading } = useValues(broadcastWizardLogic)
    const { aiComposerAvailable } = useValues(newBroadcastAgentLogic)
    // The escape hatch lands on the wizard instead (see `aiComposerAvailable`).
    const showAiComposer = id === 'new' && aiComposerAvailable
    useSceneAgentPanel({
        sceneKey: 'broadcast-new',
        contextItems: showAiComposer ? NEW_BROADCAST_COMPOSER_CONTEXT : null,
        headlines: NEW_BROADCAST_AGENT_HEADLINES,
        composer: AI_FIRST_COMPOSER_OVERRIDE,
        active: showAiComposer,
        // The composer is the page while drafting; the panel opens itself once the broadcast exists.
        autoOpen: false,
    })

    if (showAiComposer) {
        return <NewBroadcastAgent />
    }

    if (id !== 'new') {
        if (!broadcast && broadcastLoading) {
            return <SpinnerOverlay sceneLevel />
        }
        if (!broadcast) {
            return <NotFound object="broadcast" />
        }
        // Any workflow id resolves on this route. An unowned workflow shaped like a broadcast opens here
        // like one, matching the list; a workflow another product owns, or any other shape, does not.
        const isBroadcast = broadcast.origin_product === 'broadcasts'
        if (!isBroadcast && (broadcast.origin_product || !isBroadcastShaped(broadcast.actions as any))) {
            return <NotFound object="broadcast" />
        }
        // The wizard saves a broadcast back as its three-step graph, so any other graph (an edit made in the
        // workflow editor, or an agent-created one) stays read-only here rather than losing its extra steps.
        if (broadcast.status !== 'draft' || !canEditInWizard(broadcast.actions as any, broadcast.edges as any)) {
            return <BroadcastSummary />
        }
    }

    return <BroadcastWizard />
}
