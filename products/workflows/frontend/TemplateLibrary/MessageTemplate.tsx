import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonDivider, LemonTag, Spinner, SpinnerOverlay } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { EmailTemplater, TemplatePickerModal } from 'scenes/hog-functions/email-templater/EmailTemplater'
import { AI_FIRST_COMPOSER_OVERRIDE } from 'scenes/max/aiFirstCreate/aiFirstMode'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WorkflowInvocations } from '../Workflows/WorkflowInvocations'
import { workflowLogic } from '../Workflows/workflowLogic'
import { WorkflowMetrics } from '../Workflows/WorkflowMetrics'
import { WorkflowRevisions } from '../Workflows/WorkflowRevisions'
import { CodeManagedSource } from './CodeManagedSource'
import { CodeManagedTag } from './CodeManagedTag'
import { EditWithAgentButton } from './EditWithAgentButton'
import { MakeTransactionalPrompt } from './MakeTransactionalPrompt'
import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplateMenu } from './MessageTemplateMenu'
import { MessageTemplateSceneLogicProps, messageTemplateSceneLogic } from './messageTemplateSceneLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'
import { NewTemplateAgent } from './NewTemplateAgent'
import { newTemplateAgentLogic } from './newTemplateAgentLogic'
import { ReadOnlyTemplatePreview } from './ReadOnlyTemplatePreview'
import { SendTestEmailModal } from './SendTestEmailModal'
import { NEW_TEMPLATE_AGENT_HEADLINES } from './templateAgentContext'
import { TransactionalEmailApiExample } from './TransactionalEmailApiExample'

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
        setTemplatePickerOpen,
        syncExternalEdit,
        keepMyTemplateVersion,
        setTransactionalTab,
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
        transactionalHogFlowId,
        transactionalTab,
        isCodeManaged,
        isDuplicating,
        templateSource,
    } = useValues(logic)
    const transactionalEmailsEnabled = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_API')
    const showTransactional = transactionalEmailsEnabled && props.id !== 'new'

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

    const editor = (
        <div className="flex flex-col flex-1 gap-2 min-h-0 relative">
            {/* The editor stays mounted through a sync: the templater pushes the new design into the open canvas. */}
            {isSyncingExternalEdit && <SpinnerOverlay />}
            {(messageLoading || templateLoading) && !isSyncingExternalEdit ? (
                <Spinner className="text-lg" />
            ) : isCodeManaged ? (
                <ReadOnlyTemplatePreview email={originalTemplate.content.email} />
            ) : (
                <EmailTemplater
                    value={template?.content.email}
                    onChange={(value) => setTemplateValue('content.email', value)}
                    onChangeTemplating={(templating) => setTemplateValue('content.email.templating', templating)}
                    type="native_email_template"
                    layout="inline"
                />
            )}
        </div>
    )

    const tabs = (
        <LemonTabs
            activeKey={transactionalTab}
            onChange={setTransactionalTab}
            className="flex flex-col grow [&>div]:flex [&>div]:flex-col [&>div]:grow"
            tabs={[
                // Unmounting the editor would drop a canvas edit it hasn't exported yet.
                { key: 'design', label: isCodeManaged ? 'Preview' : 'Design', content: editor, keepMounted: true },
                transactionalHogFlowId
                    ? {
                          key: 'metrics',
                          label: 'Metrics',
                          content: <WorkflowMetrics id={transactionalHogFlowId} />,
                      }
                    : null,
                transactionalHogFlowId
                    ? {
                          key: 'sends',
                          label: 'Sends',
                          content: <WorkflowInvocations id={transactionalHogFlowId} />,
                      }
                    : null,
                transactionalHogFlowId
                    ? {
                          key: 'versions',
                          label: 'Versions',
                          content: <WorkflowRevisions id={transactionalHogFlowId} />,
                      }
                    : null,
                {
                    key: 'api',
                    label: 'API',
                    content: transactionalHogFlowId ? (
                        <TransactionalEmailApiExample templateId={props.id} templateKey={originalTemplate.key} />
                    ) : (
                        <MakeTransactionalPrompt {...props} />
                    ),
                },
            ]}
        />
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
                    canEdit={!isCodeManaged}
                    descriptionAlwaysVisible
                    isLoading={messageLoading || templateLoading}
                    onNameChange={(name) => setTemplateValue('name', name)}
                    onDescriptionChange={(description) => setTemplateValue('description', description)}
                    nameSuffix={
                        <>
                            {showTransactional && transactionalHogFlowId && (
                                <LemonTag type="success" className="ml-1">
                                    Transactional
                                </LemonTag>
                            )}
                            <CodeManagedTag template={originalTemplate} />
                        </>
                    }
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
                            {templateChanged && !isCodeManaged && (
                                <LemonButton
                                    data-attr="cancel-message-template"
                                    type="secondary"
                                    onClick={() => resetTemplate(originalTemplate)}
                                    size="small"
                                >
                                    Discard changes
                                </LemonButton>
                            )}
                            {isCodeManaged ? (
                                <EditWithAgentButton {...props} />
                            ) : (
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    form="template"
                                    onClick={submitTemplate}
                                    loading={isTemplateSubmitting || templateLoading}
                                    disabledReason={
                                        !templateChanged && props.id !== 'new'
                                            ? 'No changes to save'
                                            : !template.name
                                              ? 'Name is required'
                                              : undefined
                                    }
                                    size="small"
                                >
                                    {props.id === 'new' ? 'Create' : 'Save'}
                                </LemonButton>
                            )}
                            <MessageTemplateMenu {...props} />
                        </>
                    }
                />

                {(originalTemplate.key || templateSource) && (
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-secondary">
                        {originalTemplate.key && (
                            <span
                                className="flex items-center gap-1 min-w-0 max-w-full"
                                data-attr="message-template-key"
                            >
                                <span className="shrink-0">Key</span>
                                <span className="font-mono truncate min-w-0" title={originalTemplate.key}>
                                    {originalTemplate.key}
                                </span>
                                <CopyToClipboardInline
                                    explicitValue={originalTemplate.key}
                                    description="template key"
                                    iconMargin={false}
                                />
                            </span>
                        )}
                        <CodeManagedSource source={templateSource} />
                    </div>
                )}

                {isCodeManaged && (
                    <LemonBanner
                        type="info"
                        className="shrink-0"
                        action={{
                            children: 'Duplicate',
                            onClick: duplicateTemplate,
                            loading: isDuplicating,
                            'data-attr': 'message-template-code-managed-duplicate',
                        }}
                    >
                        This template is managed by code, so it can't be changed here. To change it, edit its file, or
                        let your coding agent do it.
                    </LemonBanner>
                )}

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

                {!showTransactional ? (
                    editor
                ) : transactionalHogFlowId ? (
                    // The reused workflow tabs read workflowLogic without props, so bind it to this email's workflow.
                    <BindLogic logic={workflowLogic} props={{ id: transactionalHogFlowId }}>
                        {tabs}
                    </BindLogic>
                ) : (
                    tabs
                )}
            </SceneContent>
        </Form>
    )
}
