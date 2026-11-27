import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId, useState } from 'react'

import { IconBolt, IconLock, IconTrash } from '@posthog/icons'
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
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { uuid } from 'lib/utils/dom'
import { EmailTemplater, TemplatePickerModal } from 'scenes/hog-functions/email-templater/EmailTemplater'
import { emailTemplaterLogic, saveWithLatestEmailEdit } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { AI_FIRST_COMPOSER_OVERRIDE } from 'scenes/max/aiFirstCreate/aiFirstMode'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { impactTab } from '../Transactional/impact/impactTab'
import { openEmailMetricSends } from '../Transactional/log/emailMetricSends'
import { TransactionalEmailLog } from '../Transactional/log/TransactionalEmailLog'
import { transactionalEditorGlobals, variablesInEmail } from '../Transactional/wizard/emailVariables'
import { urlForEventWorkflowWithEmailTemplate } from '../Workflows/emailTemplateWorkflowPrefill'
import { WorkflowInvocations } from '../Workflows/WorkflowInvocations'
import { workflowLogic } from '../Workflows/workflowLogic'
import { WorkflowMetrics } from '../Workflows/WorkflowMetrics'
import { WorkflowRevisions } from '../Workflows/WorkflowRevisions'
import { MakeTransactionalPrompt } from './MakeTransactionalPrompt'
import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplateSceneLogicProps, messageTemplateSceneLogic } from './messageTemplateSceneLogic'
import { MessageTemplateSceneMenuBar } from './MessageTemplateSceneMenuBar'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'
import { NewTemplateAgent } from './NewTemplateAgent'
import { newTemplateAgentLogic } from './newTemplateAgentLogic'
import { QuillMessageTemplateActions } from './QuillMessageTemplateActions'
import { SendTestEmailModal } from './SendTestEmailModal'
import { NEW_TEMPLATE_AGENT_HEADLINES } from './templateAgentContext'
import { templateWorkflowDisabledReason } from './templateWorkflowDisabledReason'
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
        setClickTrackingEnabled,
    } = useActions(logic)
    const {
        template,
        originalTemplate,
        isTemplateSubmitting,
        templateChanged,
        messageLoading,
        templateLoading,
        savedTemplateLoading,
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
        isReconcilingPublish,
        isSavingSensitive,
        isSavingClickTracking,
        isTransactional,
        section,
        failedTagSaves,
    } = useValues(logic)
    const transactionalEmailsEnabled = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_API')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    const sendLinks = useFeatureFlag('WORKFLOWS_EMAIL_SEND_LINKS')
    const impact = useFeatureFlag('WORKFLOWS_EMAIL_IMPACT')
    const showTransactional = transactionalEmailsEnabled && props.id !== 'new'

    const { setIsSaveTemplateModalOpen } = useActions(emailTemplaterLogic)
    // The editor remounts when the template loads again, and stays the same email until the person leaves the page.
    const [visitId] = useState(() => uuid())
    const sensitiveSwitchId = useId()
    const clickTrackingSwitchId = useId()

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

    const isLoaded = props.id === 'new' || originalTemplate.id === props.id
    // Only the saved template tells its type, and the two types have different headers.
    if (!isLoaded && templateLoading && transactionalEmailsEnabled && section !== 'transactional') {
        return <SpinnerOverlay sceneLevel />
    }

    const editDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor) ?? undefined
    const settingDisabledReason =
        editDisabledReason ??
        (isSavingSensitive ||
        isSavingClickTracking ||
        isTemplateSubmitting ||
        savedTemplateLoading ||
        isReconcilingPublish ||
        templateLoading ||
        isDiscardingDraft
            ? 'Wait for the current save to finish'
            : undefined)
    // Only the saved template tells its type, so until it loads the page takes the one its section mostly holds.
    const isLibraryTemplate = isLoaded ? !isTransactional : section !== 'transactional'
    const showMenuBar = sceneMenuBarEnabled && isLibraryTemplate
    const saveDisabledReason =
        editDisabledReason ??
        (isReconcilingPublish
            ? 'Wait for the current save to finish'
            : isDiscardingDraft
              ? 'Discarding your draft'
              : draftsEnabled && isSavingDraft
                ? 'Saving your draft'
                : draftsEnabled && !hasDraft && !hasUnsavedChanges
                  ? 'No changes to publish'
                  : !draftsEnabled && !templateChanged && props.id !== 'new'
                    ? 'No changes to save'
                    : !template.name
                      ? 'Name is required'
                      : undefined)
    const sendOnEventDisabledReason =
        editDisabledReason ??
        templateWorkflowDisabledReason({
            draftsEnabled,
            hasDraft,
            hasUnsavedChanges,
            templateChanged,
            isSavingSensitive,
            sensitive: !!originalTemplate.sensitive,
        })
    const sendTestDisabledReason =
        editDisabledReason ?? (!template.content.email?.subject ? 'Add a subject first' : undefined)

    const isCreating = props.id === 'new' && savedTemplateLoading
    // Tags look empty until the saved ones load, so editing them earlier would replace those.
    const canEditTags = !editDisabledReason && isLoaded && !isCreating
    const editor = (
        <div
            className="flex flex-col flex-1 gap-2 min-h-0 relative"
            // Create leaves the page and a sync replaces the form, so an edit typed meanwhile would be lost.
            {...(isCreating || isSyncingExternalEdit ? { inert: '' } : {})}
        >
            {/* The editor stays mounted through a sync: the templater pushes the new design into the open canvas. */}
            {(isSyncingExternalEdit || isCreating) && <SpinnerOverlay />}
            {(messageLoading || templateLoading) && !isSyncingExternalEdit ? (
                <Spinner className="text-lg" />
            ) : (
                <EmailTemplater
                    emailKey={`${visitId}:${props.id}`}
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

    const activeTab =
        !sendLinks && transactionalTab === 'sends'
            ? 'runs'
            : (!impact || !transactionalHogFlowId) && transactionalTab === 'impact'
              ? 'design'
              : transactionalTab
    const tabs = (
        <LemonTabs
            activeKey={activeTab}
            onChange={setTransactionalTab}
            className={cn(
                'flex flex-col grow [&>div]:flex [&>div]:flex-col [&>div]:grow',
                // The new editor scrolls on its own, so its tab fits the page. The other tabs scroll the page.
                activeTab === 'design' &&
                    'has-[[data-attr=email-document-editor]]:basis-0 has-[[data-attr=email-document-editor]]:min-h-0 has-[[data-attr=email-document-editor]]:[&>div]:basis-0 has-[[data-attr=email-document-editor]]:[&>div]:min-h-0'
            )}
            tabs={[
                // Unmounting the editor would drop a canvas edit it hasn't exported yet.
                { key: 'design', label: 'Design', content: editor, keepMounted: true },
                impact &&
                    !!transactionalHogFlowId &&
                    impactTab(transactionalHogFlowId, { alwaysSensitive: !!originalTemplate.sensitive }),
                ...(transactionalHogFlowId
                    ? [
                          {
                              key: 'metrics' as const,
                              label: 'Metrics',
                              content: (
                                  <WorkflowMetrics
                                      id={transactionalHogFlowId}
                                      transactional
                                      onEmailMetricClick={sendLinks ? openEmailMetricSends : undefined}
                                  />
                              ),
                          },
                          ...(sendLinks
                              ? [
                                    {
                                        key: 'sends' as const,
                                        label: 'Sends',
                                        content: <TransactionalEmailLog workflowId={transactionalHogFlowId} />,
                                    },
                                ]
                              : []),
                          {
                              key: 'runs' as const,
                              label: sendLinks ? 'Run logs' : 'Sends',
                              content: <WorkflowInvocations id={transactionalHogFlowId} />,
                          },
                          {
                              key: 'versions' as const,
                              label: 'Versions',
                              content: <WorkflowRevisions id={transactionalHogFlowId} />,
                          },
                      ]
                    : []),
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
                                            <label
                                                htmlFor={sensitiveSwitchId}
                                                className={
                                                    settingDisabledReason
                                                        ? 'block font-semibold'
                                                        : 'block font-semibold cursor-pointer'
                                                }
                                            >
                                                Protect sensitive data
                                            </label>
                                            <p className="text-secondary text-sm m-0 mt-1">
                                                For emails with login codes or reset links. PostHog keeps no copy of
                                                what each email contained, turns link click tracking off by default, and
                                                records only the site address when click tracking is on.
                                            </p>
                                        </div>
                                    </div>
                                    <LemonSwitch
                                        id={sensitiveSwitchId}
                                        checked={!!originalTemplate.sensitive}
                                        onChange={setSensitive}
                                        loading={isSavingSensitive}
                                        disabledReason={settingDisabledReason}
                                        data-attr="message-template-sensitive-toggle"
                                    />
                                </div>
                                {originalTemplate.sensitive && (
                                    <div className="border-t border-primary pt-3 mt-3 pl-8 flex items-start justify-between gap-4">
                                        <div className="min-w-0">
                                            <label
                                                htmlFor={clickTrackingSwitchId}
                                                className={
                                                    settingDisabledReason
                                                        ? 'block font-semibold text-sm'
                                                        : 'block font-semibold text-sm cursor-pointer'
                                                }
                                            >
                                                Track link clicks
                                            </label>
                                            <p className="text-secondary text-sm m-0 mt-1">
                                                Rewrite links to count clicks. Keep this off for links carrying login or
                                                reset tokens, or mark individual links with{' '}
                                                <code>data-ph-no-track</code>.
                                            </p>
                                        </div>
                                        <LemonSwitch
                                            id={clickTrackingSwitchId}
                                            checked={originalTemplate.click_tracking_enabled === true}
                                            onChange={setClickTrackingEnabled}
                                            loading={isSavingClickTracking}
                                            disabledReason={settingDisabledReason}
                                            data-attr="message-template-click-tracking-toggle"
                                        />
                                    </div>
                                )}
                            </LemonCard>
                            <LemonCard hoverEffect={false} className="max-w-200 p-4">
                                <div className="flex flex-wrap items-start justify-between gap-4">
                                    <div className="flex items-start gap-3 min-w-0 flex-1">
                                        <IconBolt className="text-xl text-secondary shrink-0 mt-0.5" />
                                        <div className="min-w-0">
                                            <div className="font-semibold">Send this email when an event happens</div>
                                            <p className="text-secondary text-sm m-0 mt-1">
                                                Create a workflow that sends this email to a person each time they do an
                                                event you pick, without code. Values you pass as variables in the API
                                                come from the event&apos;s properties instead. The workflow gets its own
                                                copy of the email, so later edits here don&apos;t change it.
                                            </p>
                                        </div>
                                    </div>
                                    <LemonButton
                                        type="secondary"
                                        to={urlForEventWorkflowWithEmailTemplate(props.id)}
                                        disabledReason={sendOnEventDisabledReason}
                                        data-attr="message-template-send-on-event"
                                    >
                                        Create workflow
                                    </LemonButton>
                                </div>
                            </LemonCard>
                            <TransactionalEmailApiExample templateId={props.id} />
                        </div>
                    ) : (
                        <MakeTransactionalPrompt {...props} editDisabledReason={editDisabledReason} />
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
                {showMenuBar && (
                    <MessageTemplateSceneMenuBar
                        {...props}
                        editDisabledReason={editDisabledReason}
                        saveDisabledReason={saveDisabledReason}
                        sendTestDisabledReason={sendTestDisabledReason}
                        canEditTags={canEditTags}
                    />
                )}
                <SceneTitleSection
                    name={template.name}
                    description={template.description}
                    resourceType={{ type: 'template' }}
                    canEdit={!editDisabledReason && !isCreating}
                    descriptionAlwaysVisible={!isLibraryTemplate}
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
                                    <Tooltip
                                        title={
                                            originalTemplate.click_tracking_enabled === true
                                                ? 'PostHog keeps no copy of what each email contained. Link click tracking is on and records only the site address of a clicked link.'
                                                : 'PostHog keeps no copy of what each email contained, and link click tracking is off.'
                                        }
                                    >
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
                                sendTestDisabledReason={sendTestDisabledReason}
                                saveDisabledReason={saveDisabledReason}
                                duplicateDisabledReason={
                                    editDisabledReason ??
                                    (templateChanged ? 'Save your changes before duplicating' : undefined)
                                }
                                editDisabledReason={editDisabledReason}
                                templateChanged={templateChanged && !draftsEnabled && !savedTemplateLoading}
                                saving={isTemplateSubmitting || templateLoading || savedTemplateLoading}
                                onSendTest={() => setSendTestEmailModalOpen(true)}
                                onDiscard={() => resetTemplate(originalTemplate)}
                                onSave={() => void saveWithLatestEmailEdit(submitTemplate)}
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
                                    disabledReason={sendTestDisabledReason}
                                    size="small"
                                >
                                    Send test
                                </LemonButton>
                                {templateChanged && !draftsEnabled && !savedTemplateLoading && (
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
                                    onClick={() => void saveWithLatestEmailEdit(submitTemplate)}
                                    loading={
                                        isTemplateSubmitting ||
                                        templateLoading ||
                                        savedTemplateLoading ||
                                        isReconcilingPublish
                                    }
                                    disabledReason={saveDisabledReason}
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
                                                                      disabledReason:
                                                                          editDisabledReason ??
                                                                          (!hasDraft
                                                                              ? 'There is no draft to discard'
                                                                              : isSavingDraft ||
                                                                                  isDiscardingDraft ||
                                                                                  savedTemplateLoading ||
                                                                                  isReconcilingPublish
                                                                                ? 'Wait for the draft to finish saving'
                                                                                : isSavingSensitive ||
                                                                                    isSavingClickTracking
                                                                                  ? 'Saving the setting'
                                                                                  : undefined),
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
                                                disabledReason={editDisabledReason}
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
                                                            editDisabledReason ??
                                                            (hasUnsavedChanges
                                                                ? 'Save your changes before duplicating'
                                                                : undefined)
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
                                                        disabledReason={editDisabledReason}
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

                {!showMenuBar && (
                    <SceneTags
                        // The row keeps its own copy of the tags while it is edited.
                        key={failedTagSaves}
                        tags={[...(template.tags ?? [])]}
                        onSave={saveTags}
                        canEdit={canEditTags}
                        loading={isTemplateSubmitting}
                        dataAttrKey="message-template"
                    />
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
                                    disabledReason={savedTemplateLoading ? 'Saving your changes' : undefined}
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
