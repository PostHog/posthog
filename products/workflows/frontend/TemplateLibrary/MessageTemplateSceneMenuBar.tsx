import { useActions, useValues } from 'kea'

import { IconCopy, IconScreen, IconSend, IconTrash, IconUndo, IconUpload } from '@posthog/icons'

import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { emailTemplaterLogic, saveWithLatestEmailEdit } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarPopover,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'

import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplateSceneLogicProps } from './messageTemplateSceneLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'

type MessageTemplateSceneMenuBarProps = MessageTemplateSceneLogicProps & {
    editDisabledReason?: string
    saveDisabledReason?: string
    sendTestDisabledReason?: string
    canEditTags: boolean
}

export function MessageTemplateSceneMenuBar({
    editDisabledReason,
    saveDisabledReason,
    sendTestDisabledReason,
    canEditTags,
    ...props
}: MessageTemplateSceneMenuBarProps): JSX.Element {
    const { template, originalTemplate, templateChanged, isTemplateSubmitting, templateLoading, savedTemplateLoading } =
        useValues(messageTemplateLogic(props))
    const { submitTemplate, resetTemplate, duplicateTemplate, deleteTemplate, saveTags } = useActions(
        messageTemplateLogic(props)
    )
    const { setIsSaveTemplateModalOpen } = useActions(emailTemplaterLogic)
    const { setModalOpen: setSendTestEmailModalOpen } = useActions(messageTemplateTestSendLogic(props))
    const isNew = props.id === 'new'
    const duplicateDisabledReason =
        editDisabledReason ?? (templateChanged ? 'Save your changes before duplicating' : undefined)

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr="message-template-menubar-file">
                <SceneMenuBarItem
                    onClick={() => void saveWithLatestEmailEdit(submitTemplate)}
                    disabled={!!saveDisabledReason || isTemplateSubmitting || templateLoading || savedTemplateLoading}
                    tooltip={saveDisabledReason}
                    data-attr="message-template-menubar-save"
                >
                    <IconUpload />
                    {isNew ? 'Create' : 'Save'}
                </SceneMenuBarItem>
                {!isNew && (
                    <>
                        <SceneMenuBarSeparator />
                        <SceneMenuBarItem
                            variant="destructive"
                            onClick={() => deleteTemplate()}
                            disabled={!!editDisabledReason}
                            tooltip={editDisabledReason}
                            data-attr="message-template-menubar-delete"
                        >
                            <IconTrash />
                            Delete
                        </SceneMenuBarItem>
                    </>
                )}
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="Edit" dataAttr="message-template-menubar-edit">
                <SceneMenuBarItem
                    opensFloatingUi
                    onClick={() => setSendTestEmailModalOpen(true)}
                    disabled={!!sendTestDisabledReason}
                    tooltip={sendTestDisabledReason}
                    data-attr="message-template-menubar-send-test"
                >
                    <IconSend />
                    Send test
                </SceneMenuBarItem>
                {!isNew && (
                    <SceneMenuBarItem
                        onClick={() => duplicateTemplate()}
                        disabled={!!duplicateDisabledReason}
                        tooltip={duplicateDisabledReason}
                        data-attr="message-template-menubar-duplicate"
                    >
                        <IconCopy />
                        Duplicate
                    </SceneMenuBarItem>
                )}
                <SceneMenuBarItem
                    opensFloatingUi
                    onClick={() => setIsSaveTemplateModalOpen(true)}
                    disabled={!!editDisabledReason}
                    tooltip={editDisabledReason}
                    data-attr="message-template-menubar-save-as-new"
                >
                    <IconScreen />
                    Save as new template
                </SceneMenuBarItem>
                {templateChanged && !savedTemplateLoading && (
                    <SceneMenuBarItem
                        onClick={() => resetTemplate(originalTemplate)}
                        data-attr="message-template-menubar-discard"
                    >
                        <IconUndo />
                        Discard changes
                    </SceneMenuBarItem>
                )}
            </SceneMenuBarMenu>
            <SceneMenuBarPopover
                label="Metadata"
                dataAttr="message-template-menubar-metadata"
                contentClassName="w-80 p-2 flex flex-col gap-2"
            >
                <SceneTagsCombobox
                    tags={[...(template.tags ?? [])]}
                    onSave={saveTags}
                    canEdit={canEditTags}
                    loading={isTemplateSubmitting}
                    dataAttrKey="message-template"
                />
            </SceneMenuBarPopover>
        </SceneMenuBar>
    )
}
