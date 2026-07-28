import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonDivider, Spinner, SpinnerOverlay } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { EmailTemplater } from 'scenes/hog-functions/email-templater/EmailTemplater'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplateSceneLogicProps, messageTemplateSceneLogic } from './messageTemplateSceneLogic'

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
        loadTemplate,
        setExternallyEdited,
    } = useActions(logic)
    const {
        template,
        originalTemplate,
        isTemplateSubmitting,
        templateChanged,
        messageLoading,
        externallyEdited,
        isSyncingExternalEdit,
    } = useValues(logic)

    const { toggleTemplatePicker, setIsSaveTemplateModalOpen } = useActions(emailTemplaterLogic)
    const { templates, isTemplatePickerExpanded } = useValues(emailTemplaterLogic)

    // Attach template logic to scene logic so it persists across tab switches
    useAttachedLogic(logic, sceneLogic)

    useAttachedContext(
        props.id && props.id !== 'new'
            ? [{ type: 'email_template', key: props.id, label: template?.name || undefined }]
            : null
    )

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
                    isLoading={messageLoading}
                    onNameChange={(name) => setTemplateValue('name', name)}
                    onDescriptionChange={(description) => setTemplateValue('description', description)}
                    actions={
                        <>
                            {templates.length > 0 && (
                                <LemonButton
                                    data-attr="start-from-template"
                                    type="secondary"
                                    size="small"
                                    active={isTemplatePickerExpanded}
                                    onClick={() => toggleTemplatePicker()}
                                >
                                    Start from template
                                </LemonButton>
                            )}
                            <LemonButton
                                data-attr="save-as-new-template"
                                type="secondary"
                                size="small"
                                onClick={() => setIsSaveTemplateModalOpen(true)}
                            >
                                Save as new template
                            </LemonButton>
                            {props.id !== 'new' && (
                                <>
                                    <More
                                        size="small"
                                        overlay={
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
                                        }
                                    />
                                    <LemonDivider vertical />
                                </>
                            )}
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
                                disabledReason={templateChanged ? undefined : 'No changes to save'}
                                size="small"
                            >
                                {props.id === 'new' ? 'Create' : 'Save'}
                            </LemonButton>
                        </>
                    }
                />

                <div className="flex flex-col flex-1 gap-2 min-h-0 relative">
                    {isSyncingExternalEdit && <SpinnerOverlay />}
                    {externallyEdited && (
                        <LemonBanner type="warning" className="shrink-0">
                            <div className="flex items-center justify-between gap-2">
                                <span>
                                    This template was updated elsewhere (for example by an AI assistant) while you have
                                    unsaved changes. Reload to get the latest version, or keep editing. Saving will
                                    overwrite the other changes.
                                </span>
                                <div className="flex items-center gap-2 shrink-0">
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => setExternallyEdited(false)}
                                    >
                                        Keep mine
                                    </LemonButton>
                                    <LemonButton type="primary" size="small" onClick={() => loadTemplate()}>
                                        Reload
                                    </LemonButton>
                                </div>
                            </div>
                        </LemonBanner>
                    )}
                    {messageLoading ? (
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
