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

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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

import { transactionalEditorGlobals, variablesInEmail } from '../Transactional/wizard/emailVariables'
import { WorkflowInvocations } from '../Workflows/WorkflowInvocations'
import { workflowLogic } from '../Workflows/workflowLogic'
import { WorkflowMetrics } from '../Workflows/WorkflowMetrics'
import { WorkflowRevisions } from '../Workflows/WorkflowRevisions'
import { CodeManagedSource } from './CodeManagedSource'
import { CodeManagedTag } from './CodeManagedTag'
import { MakeTransactionalPrompt } from './MakeTransactionalPrompt'
import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplateMenu } from './MessageTemplateMenu'
import { MessageTemplateSceneLogicProps, messageTemplateSceneLogic } from './messageTemplateSceneLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'
import { NewTemplateAgent } from './NewTemplateAgent'
import { newTemplateAgentLogic } from './newTemplateAgentLogic'
import { QuillMessageTemplateActions } from './QuillMessageTemplateActions'
import { ReadOnlyTemplatePreview } from './ReadOnlyTemplatePreview'
import { DUPLICATE_REFUSED_EDITS_REASON, RefusedEditsBanner } from './RefusedEditsBanner'
import { openReleaseTemplateDialog } from './releaseTemplateDialog'
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
        releaseTemplate,
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
        isCodeManaged,
        isDuplicating,
        refusedEdits,
        templateSource,
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
            ) : isCodeManaged ? (
                <ReadOnlyTemplatePreview email={originalTemplate.content.email} />
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
                    variables={
                        template?.transactional_hog_flow_id
                            ? transactionalEditorGlobals(variablesInEmail(template.content.email))
                            : undefined
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
                        <div className="flex flex-col gap-4">
                            <LemonCard hoverEffect={false} className="max-w-200 p-4">
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex items-start gap-3 min-w-0">
                                        <IconLock className="text-xl text-secondary shrink-0 mt-0.5" />
                                        <div className="min-w-0">
                                            <div className="font-semibold">Protect sensitive data</div>
                                            <p className="text-secondary text-sm m-0 mt-1">
                                                For emails with login codes or reset links. PostHog keeps no copy of
                                                what each email contained, and doesn&apos;t track link clicks.
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
                            <TransactionalEmailApiExample templateId={props.id} templateKey={originalTemplate.key} />
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
                    canEdit={!isCodeManaged}
                    descriptionAlwaysVisible
                    isLoading={messageLoading || templateLoading}
                    onNameChange={(name) => setTemplateValue('name', name)}
                    onDescriptionChange={(description) => setTemplateValue('description', description)}
                    nameSuffix={
                        <>
                            {showTransactional && transactionalHogFlowId && (
                                <>
                                    <LemonTag type="success" className="ml-1">
                                        Transactional
                                    </LemonTag>
                                    {originalTemplate.sensitive && (
                                        <Tooltip title="PostHog keeps no copy of what each email contained, and doesn't track link clicks.">
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
                            )}
                            <CodeManagedTag template={originalTemplate} />
                        </>
                    }
                    actions={
                        todayRailNav ? (
                            <QuillMessageTemplateActions
                                isNew={props.id === 'new'}
                                sendTestDisabledReason={
                                    !template.content.email?.subject ? 'Add a subject first' : undefined
                                }
                                saveDisabledReason={
                                    isCodeManaged
                                        ? 'This template is managed by code'
                                        : draftsEnabled && isSavingDraft
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
                                    isDuplicating
                                        ? 'Duplicating…'
                                        : refusedEdits
                                          ? DUPLICATE_REFUSED_EDITS_REASON
                                          : templateChanged
                                            ? 'Save your changes before duplicating'
                                            : undefined
                                }
                                templateChanged={templateChanged && !draftsEnabled && !isCodeManaged}
                                saving={isTemplateSubmitting || templateLoading}
                                onSendTest={() => setSendTestEmailModalOpen(true)}
                                onDiscard={() => resetTemplate(originalTemplate)}
                                onSave={submitTemplate}
                                onSaveAsNew={isCodeManaged ? undefined : () => setIsSaveTemplateModalOpen(true)}
                                onDuplicate={duplicateTemplate}
                                onRelease={
                                    isCodeManaged
                                        ? () => openReleaseTemplateDialog(originalTemplate, releaseTemplate)
                                        : undefined
                                }
                                releaseDisabledReason={templateLoading ? 'Wait for the template to load' : undefined}
                                deleteDisabledReason={
                                    isCodeManaged
                                        ? 'This template is managed by code. To delete it, stop managing it in code first.'
                                        : undefined
                                }
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
                                {templateChanged && !draftsEnabled && !isCodeManaged && (
                                    <LemonButton
                                        data-attr="cancel-message-template"
                                        type="secondary"
                                        onClick={() => resetTemplate(originalTemplate)}
                                        size="small"
                                    >
                                        Discard changes
                                    </LemonButton>
                                )}
                                {!isCodeManaged && (
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
                                )}
                                <MessageTemplateMenu {...props} />
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

                <RefusedEditsBanner {...props} />

                {isCodeManaged && (
                    <LemonBanner
                        type="info"
                        className="shrink-0"
                        action={
                            refusedEdits
                                ? undefined
                                : {
                                      children: 'Duplicate',
                                      onClick: duplicateTemplate,
                                      loading: isDuplicating,
                                      'data-attr': 'message-template-code-managed-duplicate',
                                  }
                        }
                    >
                        This template is managed by code, so it can't be changed here. To change it, edit the file and
                        upload it again. To edit it here, duplicate it or stop managing it in code.
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
