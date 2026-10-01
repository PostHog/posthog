import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

export const scene: SceneExport = {
    component: AudienceScene,
    productKey: ProductKey.WORKFLOWS,
}

export function AudienceScene(): JSX.Element {
    return <></>
}
