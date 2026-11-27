import { useValues } from 'kea'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'

import { MessageAudienceShown, MessageAudienceShownProps } from './MessageAudienceShown'

const INLINE_SCENE_PANEL = '.scene-layout__content-panel'

export function MessageAudienceShownInScenePanel(props: MessageAudienceShownProps): JSX.Element | null {
    const { scenePanelOpen, scenePanelElement } = useValues(sceneLayoutLogic)
    const inActionsPane = !!scenePanelElement && !scenePanelElement.closest(INLINE_SCENE_PANEL)
    return scenePanelOpen || inActionsPane ? <MessageAudienceShown {...props} /> : null
}
