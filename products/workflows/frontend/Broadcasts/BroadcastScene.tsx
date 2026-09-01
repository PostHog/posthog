import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { BroadcastSummary } from './BroadcastSummary'
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
                <BroadcastSceneContent id={logicProps.id} />
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
