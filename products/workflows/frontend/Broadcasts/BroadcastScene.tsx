import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

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
            <BroadcastSceneContent id={logicProps.id} />
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
        if (broadcast.status !== 'draft') {
            return <BroadcastSummary />
        }
    }

    return <BroadcastWizard />
}
