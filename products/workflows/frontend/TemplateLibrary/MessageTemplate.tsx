import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonDivider, Spinner, SpinnerOverlay } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { EmailTemplater, TemplatePickerModal } from 'scenes/hog-functions/email-templater/EmailTemplater'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { AI_FIRST_COMPOSER_OVERRIDE } from 'scenes/max/aiFirstCreate/aiFirstMode'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplateSceneLogicProps, messageTemplateSceneLogic } from './messageTemplateSceneLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'
import { NewTemplateAgent } from './NewTemplateAgent'
import { newTemplateAgentLogic } from './newTemplateAgentLogic'
import { SendTestEmailModal } from './SendTestEmailModal'
import { NEW_TEMPLATE_AGENT_HEADLINES } from './templateAgentContext'

export const scene: SceneExport<MessageTemplateSceneLogicProps> = {
    component: MessageTemplate,
    logic: messageTemplateSceneLogic,
    paramsToProps: ({ params: { id }, searchParams: { messageId } }) => ({
        id: id || 'new',
        messageId,
    }),
    productKey: ProductKey.WORKFLOWS,
}

export function MessageTemplate(props: MessageTemplateSceneLogicProps): JSX.Element {
    const sceneLogic = messageTemplateSceneLogic(props)
    const logic = messageTemplateLogic(props)
    const {
        submitTemplate,
        resetTemplate,
        setTemplateValue,
        duplicateTemplate,
        deleteTemplate,
        setTemplatePickerOpen,
        syncExternalEdit,
        keepMyTemplateVersion,
    } = useActions(logic)
    const {
        template,
        originalTemplate,
        isTemplateSubmitting,
        templateChanged,
        messageLoading,
        templateLoading,
        templatePickerOpen,
        externallyEdited,
        isSyncingExternalEdit,
    } = useValues(logic)

    const { setIsSaveTemplateModalOpen } = useActions(emailTemplaterLogic)

    const testSendLogic = messageTemplateTestSendLogic(props)
    const { isModalOpen: isSendTestEmailModalOpen } = useValues(testSendLogic)
    const { setModalOpen: setSendTestEmailModalOpen } = useActions(testSendLogic)

    // Attach template logic to scene logic so it persists across tab switches
    useAttachedLogic(logic, sceneLogic)

    const { aiComposerAvailable, agentContextItems } = useValues(newTemplateAgentLogic)
    // A template started from a sent message, and the escape hatch, land in the editor instead (see `aiComposerAvailable`).
    const showAiComposer = props.id === 'new' && aiComposerAvailable
    useSceneAgentPanel({
        sceneKey: 'email-template',
        contextItems: showAiComposer ? agentContextItems : null,
        headlines: NEW_TEMPLATE_AGENT_HEADLINES,
        composer: AI_FIRST_COMPOSER_OVERRIDE,
        active: showAiComposer,
        // The composer is the page while drafting; the panel opens itself once the template exists.
        autoOpen: false,
    })

    if (showAiComposer) {
        return (
            <SceneContent className="h-full flex flex-col grow" data-attr="message-template-scene">
                <NewTemplateAgent />
            </SceneContent>
        )
    }

    return (
        <Form
            logic={messageTemplateLogic}
            formKey="template"
            props={props}
            {...{ className: 'flex flex-col grow h-full' }}
        >
            <SceneContent className="h-full flex flex-col grow">
                <SceneTitleSection
                    name={template.name}
                    description={template.description}
                    resourceType={{ type: 'template' }}
                    canEdit
                    descriptionAlwaysVisible
                    isLoading={messageLoading || templateLoading}
                    onNameChange={(name) => setTemplateValue('name', name)}
                    onDescriptionChange={(description) => setTemplateValue('description', description)}
                    actions={
                        <>
                            <LemonDivider vertical />
                            <LemonButton
                                data-attr="send-test-message-template"
                                type="secondary"
                                onClick={() => setSendTestEmailModalOpen(true)}
                                disabledReason={!template.content.email?.subject ? 'Add a subject first' : undefined}
                                size="small"
                            >
                                Send test
                            </LemonButton>
                            {templateChanged && (
                                <LemonButton
                                    data-attr="cancel-message-template"
                                    type="secondary"
                                    onClick={() => resetTemplate(originalTemplate)}
                                    size="small"
                                >
                                    Discard changes
                                </LemonButton>
                            )}
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                form="template"
                                onClick={submitTemplate}
                                loading={isTemplateSubmitting}
                                disabledReason={
                                    !templateChanged
                                        ? 'No changes to save'
                                        : !template.name
                                          ? 'Name is required'
                                          : undefined
                                }
                                size="small"
                            >
                                {props.id === 'new' ? 'Create' : 'Save'}
                            </LemonButton>
                            <More
                                size="small"
                                overlay={
                                    <>
                                        <LemonButton
                                            data-attr="save-as-new-template"
                                            fullWidth
                                            onClick={() => setIsSaveTemplateModalOpen(true)}
                                        >
                                            Save as new template
                                        </LemonButton>
                                        {props.id !== 'new' && (
                                            <>
                                                <LemonButton
                                                    data-attr="duplicate-message-template"
                                                    fullWidth
                                                    onClick={duplicateTemplate}
                                                    disabledReason={
                                                        templateChanged
                                                            ? 'Save your changes before duplicating'
                                                            : undefined
                                                    }
                                                >
                                                    Duplicate
                                                </LemonButton>
                                                <LemonDivider />
                                                <LemonButton
                                                    data-attr="delete-message-template"
                                                    status="danger"
                                                    fullWidth
                                                    onClick={deleteTemplate}
                                                >
                                                    Delete
                                                </LemonButton>
                                            </>
                                        )}
                                    </>
                                }
                            />
                        </>
                    }
                />

                <TemplatePickerModal isOpen={templatePickerOpen} onClose={() => setTemplatePickerOpen(false)} />
                <SendTestEmailModal {...props} isOpen={isSendTestEmailModalOpen} />

                {externallyEdited && (
                    <LemonBanner type="warning">
                        <div className="flex items-center justify-between gap-2">
                            <span>
                                This template was updated elsewhere (for example via the API or an AI assistant) while
                                you have unsaved changes. Reload to get the latest version, or keep editing and save to
                                overwrite the other changes.
                            </span>
                            <div className="flex items-center gap-2 shrink-0">
                                <LemonButton type="secondary" size="small" onClick={() => keepMyTemplateVersion()}>
                                    Keep mine
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={() => syncExternalEdit()}
                                    loading={isSyncingExternalEdit}
                                >
                                    Reload
                                </LemonButton>
                            </div>
                        </div>
                    </LemonBanner>
                )}

                <div className="flex flex-col flex-1 gap-2 min-h-0 relative">
                    {/* The editor stays mounted through a sync: the templater pushes the new design into the open canvas. */}
                    {isSyncingExternalEdit && <SpinnerOverlay />}
                    {(messageLoading || templateLoading) && !isSyncingExternalEdit ? (
                        <Spinner className="text-lg" />
                    ) : (
                        <EmailTemplater
                            value={template?.content.email}
                            onChange={(value) => setTemplateValue('content.email', value)}
                            onChangeTemplating={(templating) =>
                                setTemplateValue('content.email.templating', templating)
                            }
                            type="native_email_template"
                            layout="inline"
                        />
                    )}
                </div>
            </SceneContent>
        </Form>
    )
}
