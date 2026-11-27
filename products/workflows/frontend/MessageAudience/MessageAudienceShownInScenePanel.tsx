import { useValues } from 'kea'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'

import { MessageAudienceShown, MessageAudienceShownProps } from './MessageAudienceShown'

export function MessageAudienceShownInScenePanel(props: MessageAudienceShownProps): JSX.Element | null {
    const { scenePanelOpen } = useValues(sceneLayoutLogic)
    return scenePanelOpen ? <MessageAudienceShown {...props} /> : null
}
