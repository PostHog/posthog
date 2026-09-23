import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { ProductKey } from '~/queries/schema/schema-general'

import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { isBroadcastShaped, isEligibleWorkflow } from './broadcastsLogic'
import { BroadcastSummary } from './BroadcastSummary'
import { broadcastTestSendLogic } from './broadcastTestSendLogic'
import { BroadcastWizard } from './BroadcastWizard'
import { BroadcastWizardLogicProps, broadcastWizardLogic } from './broadcastWizardLogic'
import { broadcastsFeaturePreviewGate } from './featurePreviewGate'

export const scene: SceneExport<BroadcastWizardLogicProps> = {
    component: BroadcastScene,
    logic: broadcastWizardLogic,
    paramsToProps: ({ params: { id } }): BroadcastWizardLogicProps => ({ id: id || 'new' }),
    productKey: ProductKey.WORKFLOWS,
}

export function BroadcastScene({ id }: BroadcastWizardLogicProps): JSX.Element {
    const logicProps: BroadcastWizardLogicProps = { id: id || 'new' }

    return (
        <FeaturePreviewSceneGate config={broadcastsFeaturePreviewGate}>
            <BindLogic logic={broadcastWizardLogic} props={logicProps}>
                <BindLogic logic={broadcastPreviewLogic} props={logicProps}>
                    <BindLogic logic={broadcastTestSendLogic} props={logicProps}>
                        <BroadcastSceneContent id={logicProps.id} />
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </FeaturePreviewSceneGate>
    )
}

function BroadcastSceneContent({ id }: BroadcastWizardLogicProps): JSX.Element {
    const { broadcast, broadcastLoading, isReadOnly } = useValues(broadcastWizardLogic)
    if (id !== 'new') {
        if (!broadcast && broadcastLoading) {
            return <SpinnerOverlay sceneLevel />
        }
        if (!broadcast) {
            return <NotFound object="broadcast" />
        }
        // Any workflow id resolves on this route, and the wizard would rewrite whatever graph it
        // opened into a broadcast's trigger/email/exit on the next save.
        if (isEligibleWorkflow(broadcast) && !isBroadcastShaped(broadcast)) {
            return <NotFound object="broadcast" />
        }
        if (isReadOnly) {
            return <BroadcastSummary />
        }
    }

    // A new broadcast opens on the AI screen, so the fastest path is describing the send rather than
    // walking five steps. The wizard stays one click away and is the only path for an existing draft.

    return <BroadcastWizard />
}
