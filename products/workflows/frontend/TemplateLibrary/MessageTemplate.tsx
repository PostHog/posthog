import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconLock, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonDivider,
    LemonMenuOverlay,
    LemonSwitch,
    LemonTag,
    Spinner,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'

import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { EmailTemplater, TemplatePickerModal } from 'scenes/hog-functions/email-templater/EmailTemplater'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
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
import { MakeTransactionalPrompt } from './MakeTransactionalPrompt'
import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplateSceneLogicProps, messageTemplateSceneLogic } from './messageTemplateSceneLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'
import { NewTemplateAgent } from './NewTemplateAgent'
import { newTemplateAgentLogic } from './newTemplateAgentLogic'
import { QuillMessageTemplateActions } from './QuillMessageTemplateActions'
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
        deleteTemplate,
        setTemplatePickerOpen,
        syncExternalEdit,
        keepMyTemplateVersion,
        setTransactionalTab,
        discardDraft,
        saveTags,
        setSensitive,
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
        draftsEnabled,
        hasDraft,
        hasUnsavedChanges,
        isSavingDraft,
        isDiscardingDraft,
        isSavingSensitive,
    } = useValues(logic)
    const transactionalEmailsEnabled = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_API')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const showTransactional = transactionalEmailsEnabled && props.id !== 'new'

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

    const editor = (
        <div className="flex flex-col flex-1 gap-2 min-h-0 relative">
            {/* The editor stays mounted through a sync: the templater pushes the new design into the open canvas. */}
            {isSyncingExternalEdit && <SpinnerOverlay />}
            {(messageLoading || templateLoading) && !isSyncingExternalEdit ? (
                <Spinner className="text-lg" />
            ) : (
                <EmailTemplater
                    value={template?.content.email}
                    onChange={(value) => setTemplateValue('content.email', value)}
                    onChangeTemplating={(templating) => setTemplateValue('content.email.templating', templating)}
                    type={
                        template?.transactional_hog_flow_id
                            ? 'native_email_transactional_template'
                            : 'native_email_template'
                    }
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
                { key: 'design', label: 'Design', content: editor, keepMounted: true },
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
                        <div className="flex flex-col gap-4">
                            <LemonCard hoverEffect={false} className="max-w-200 p-4">
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex items-start gap-3 min-w-0">
                                        <IconLock className="text-xl text-secondary shrink-0 mt-0.5" />
                                        <div className="min-w-0">
                                            <div className="font-semibold">Protect sensitive data</div>
                                            <p className="text-secondary text-sm m-0 mt-1">
                                                For emails with login codes or reset links. PostHog keeps no copy of
                                                what each email contained, and clicked links keep only the site address.
                                            </p>
                                        </div>
                                    </div>
                                    <LemonSwitch
                                        checked={!!originalTemplate.sensitive}
                                        onChange={setSensitive}
                                        loading={isSavingSensitive}
                                        disabledReason={isSavingSensitive ? 'Saving the setting' : undefined}
                                        aria-label="Protect sensitive data"
                                        data-attr="message-template-sensitive-toggle"
                                    />
                                </div>
                            </LemonCard>
                            <TransactionalEmailApiExample templateId={props.id} />
                        </div>
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
                    canEdit
                    descriptionAlwaysVisible
                    isLoading={messageLoading || templateLoading}
                    onNameChange={(name) => setTemplateValue('name', name)}
                    onDescriptionChange={(description) => setTemplateValue('description', description)}
                    nameSuffix={
                        showTransactional && transactionalHogFlowId ? (
                            <>
                                <LemonTag type="success" className="ml-1">
                                    Transactional
                                </LemonTag>
                                {originalTemplate.sensitive && (
                                    <Tooltip title="PostHog keeps no copy of what each email contained, and clicked links keep only the site address.">
                                        <LemonTag
                                            type="highlight"
                                            icon={<IconLock />}
                                            className="ml-1"
                                            data-attr="message-template-sensitive-tag"
                                        >
                                            Sensitive
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {(hasDraft || hasUnsavedChanges) && (
                                    <Tooltip title="Your changes save as a draft. Sends use the live version until you publish.">
                                        <LemonTag
                                            type="warning"
                                            className="ml-1"
                                            data-attr="message-template-draft-tag"
                                        >
                                            {isSavingDraft ? 'Saving draft…' : 'Editing draft'}
                                        </LemonTag>
                                    </Tooltip>
                                )}
                            </>
                        ) : undefined
                    }
                    actions={
                        todayRailNav ? (
                            <QuillMessageTemplateActions
                                isNew={props.id === 'new'}
                                sendTestDisabledReason={
                                    !template.content.email?.subject ? 'Add a subject first' : undefined
                                }
                                saveDisabledReason={
                                    draftsEnabled && isSavingDraft
                                        ? 'Saving your draft'
                                        : draftsEnabled && !hasDraft && !hasUnsavedChanges
                                          ? 'No changes to publish'
                                          : !draftsEnabled && !templateChanged && props.id !== 'new'
                                            ? 'No changes to save'
                                            : !template.name
                                              ? 'Name is required'
                                              : undefined
                                }
                                duplicateDisabledReason={
                                    templateChanged ? 'Save your changes before duplicating' : undefined
                                }
                                templateChanged={templateChanged && !draftsEnabled}
                                saving={isTemplateSubmitting || templateLoading}
                                onSendTest={() => setSendTestEmailModalOpen(true)}
                                onDiscard={() => resetTemplate(originalTemplate)}
                                onSave={submitTemplate}
                                onSaveAsNew={() => setIsSaveTemplateModalOpen(true)}
                                onDuplicate={duplicateTemplate}
                                onDelete={deleteTemplate}
                            />
                        ) : (
                            <>
                                <LemonDivider vertical />
                                <LemonButton
                                    data-attr="send-test-message-template"
                                    type="secondary"
                                    onClick={() => setSendTestEmailModalOpen(true)}
                                    disabledReason={
                                        !template.content.email?.subject ? 'Add a subject first' : undefined
                                    }
                                    size="small"
                                >
                                    Send test
                                </LemonButton>
                                {templateChanged && !draftsEnabled && (
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
                                    loading={isTemplateSubmitting || templateLoading}
                                    disabledReason={
                                        draftsEnabled && isSavingDraft
                                            ? 'Saving your draft'
                                            : draftsEnabled && !hasDraft && !hasUnsavedChanges
                                              ? 'No changes to publish'
                                              : !draftsEnabled && !templateChanged && props.id !== 'new'
                                                ? 'No changes to save'
                                                : !template.name
                                                  ? 'Name is required'
                                                  : undefined
                                    }
                                    size="small"
                                    sideAction={
                                        draftsEnabled
                                            ? {
                                                  'data-attr': 'message-template-draft-actions',
                                                  'aria-label': 'More draft actions',
                                                  dropdown: {
                                                      placement: 'bottom-end',
                                                      overlay: (
                                                          <LemonMenuOverlay
                                                              items={[
                                                                  {
                                                                      label: 'Discard draft',
                                                                      icon: <IconTrash />,
                                                                      status: 'danger',
                                                                      onClick: discardDraft,
                                                                      disabledReason: !hasDraft
                                                                          ? 'There is no draft to discard'
                                                                          : isSavingDraft || isDiscardingDraft
                                                                            ? 'Wait for the draft to finish saving'
                                                                            : undefined,
                                                                      'data-attr': 'message-template-discard-draft',
                                                                  },
                                                              ]}
                                                          />
                                                      ),
                                                  },
                                              }
                                            : undefined
                                    }
                                >
                                    {props.id === 'new' ? 'Create' : draftsEnabled ? 'Publish' : 'Save'}
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
                                                            hasUnsavedChanges
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
                        )
                    }
                />

                <SceneTags
                    tags={[...(template.tags ?? [])]}
                    onSave={saveTags}
                    loading={isTemplateSubmitting}
                    dataAttrKey="message-template"
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
