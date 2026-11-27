import { useValues } from 'kea'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'

import { MessageAudienceShown, MessageAudienceShownProps } from './MessageAudienceShown'

const INLINE_SCENE_PANEL = '.scene-layout__content-panel'

export function MessageAudienceShownInScenePanel(props: MessageAudienceShownProps): JSX.Element | null {
    const { scenePanelOpenManual, scenePanelElement } = useValues(sceneLayoutLogic)
    const hostVisible = scenePanelElement?.closest(INLINE_SCENE_PANEL) ? scenePanelOpenManual : !!scenePanelElement
    return hostVisible ? <MessageAudienceShown {...props} /> : null
}
