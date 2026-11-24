import { useActions, useValues } from 'kea'

import { SceneTags } from 'lib/components/Scenes/SceneTags'

import { SceneDescription } from '~/layout/scenes/components/SceneDescription'
import { ScenePanel, ScenePanelInfoSection, ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplateSceneLogicProps } from './messageTemplateSceneLogic'

export function MessageTemplateScenePanel({
    canEdit,
    ...props
}: MessageTemplateSceneLogicProps & { canEdit: boolean }): JSX.Element {
    const { template, isTemplateSubmitting } = useValues(messageTemplateLogic(props))
    const { saveTags, setTemplateValue } = useActions(messageTemplateLogic(props))

    return (
        <ScenePanel>
            <ScenePanelInfoSection>
                <SceneTags
                    tags={[...(template.tags ?? [])]}
                    onSave={saveTags}
                    canEdit={canEdit}
                    loading={isTemplateSubmitting}
                    dataAttrKey="message-template"
                />
                <ScenePanelLabel title="Description">
                    <SceneDescription
                        description={template.description || null}
                        onChange={(description) => setTemplateValue('description', description)}
                        canEdit={canEdit}
                    />
                </ScenePanelLabel>
            </ScenePanelInfoSection>
        </ScenePanel>
    )
}
