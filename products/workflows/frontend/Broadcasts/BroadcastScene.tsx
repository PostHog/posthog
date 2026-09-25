import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { canEditInWizard, isBroadcastShaped } from './broadcastsLogic'
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
    const { broadcast, broadcastLoading } = useValues(broadcastWizardLogic)

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
        if (
            broadcast.status !== 'draft' ||
            (!isBroadcast && !canEditInWizard(broadcast.actions as any, broadcast.edges as any))
        ) {
            return <BroadcastSummary />
        }
    }

    return <BroadcastWizard />
}
