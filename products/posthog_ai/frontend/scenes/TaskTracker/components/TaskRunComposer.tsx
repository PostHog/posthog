import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { type MutableRefObject, type RefObject, useEffect } from 'react'

import { projectLogic } from 'scenes/projectLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { runInteractionLogic, type RunInteractionLogicProps } from 'products/posthog_ai/frontend/api/logics'
import { Composer, QueuedMessageList } from 'products/posthog_ai/frontend/api/primitives'
import { modelCatalogueLogic } from 'products/posthog_ai/frontend/logics/modelCatalogueLogic'
import { taskRunDefaultsLogic } from 'products/posthog_ai/frontend/logics/taskRunDefaultsLogic'
import { getRuntimeAdapterForModel } from 'products/posthog_ai/frontend/utils/composerModels'
import { cycleMode, getModesForRuntimeAdapter } from 'products/posthog_ai/frontend/utils/composerModes'

import { AttachedContextBar } from '../../../components/composer/AttachedContextBar'
import { ComposerModelEffortPickers } from '../../../components/composer/ComposerModelEffortPickers'
import { ComposerModePicker } from '../../../components/composer/ComposerModePicker'
import { ComposerModeShortcut } from '../../../components/composer/ComposerModeShortcut'
import { useDebouncedDraft } from '../../../components/composer/useDebouncedDraft'
import { ContextUsageChip } from '../../../components/ContextUsageChip'

export function TaskRunComposer({
    logicProps,
    textAreaRef,
    autoFocus,
    flushDraftRef,
}: {
    logicProps: RunInteractionLogicProps
    textAreaRef: RefObject<HTMLTextAreaElement>
    autoFocus?: boolean
    flushDraftRef: MutableRefObject<() => void>
}): JSX.Element {
    const {
        composerForm,
        draftRecovery,
        canSend,
        isSubmitting,
        isBusy,
        queuedMessages,
        isTerminal,
        selectedModel,
        defaultModel,
        selectedEffort,
        consentBlocked,
        selectedMode,
        composerActive,
        steerPending,
        cancellationState,
    } = useValues(runInteractionLogic(logicProps))
    const { catalogue } = useValues(modelCatalogueLogic)
    const { user } = useValues(userLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { myConfigLoading } = useValues(taskRunDefaultsLogic)
    // A live run's harness is whatever it booted on; once terminal the next run follows the picked model.
    const composerAdapter = logicProps.currentRuntimeAdapter ?? getRuntimeAdapterForModel(catalogue, selectedModel)
    const controlsReady = isTerminal || !!logicProps.currentRuntimeAdapter
    const {
        setComposerFormValues,
        enableTaskDraftPersistence,
        setComposerFocused,
        submitComposerForm,
        requestCancellation,
        updateQueuedMessage,
        removeQueuedMessage,
        setModel,
        setEffort,
        clearConsentBlock,
        setMode,
        steerQueue,
        submitAfterConsent,
    } = useActions(runInteractionLogic(logicProps))

    useEffect(() => {
        if (user?.uuid && currentProjectId !== null) {
            enableTaskDraftPersistence(user.uuid, currentProjectId)
        }
    }, [user?.uuid, currentProjectId, enableTaskDraftPersistence])

    const draft = useDebouncedDraft(composerForm.draft, (value) => setComposerFormValues({ draft: value }))
    useEffect(() => {
        flushDraftRef.current = draft.flush
    }, [flushDraftRef, draft.flush])

    return (
        <div onFocusCapture={() => setComposerFocused(true)} onBlurCapture={() => setComposerFocused(false)}>
            <ComposerModeShortcut
                disabled={!composerActive || !controlsReady}
                onCycle={() => setMode(cycleMode(composerAdapter, selectedMode))}
            />
            <Composer.Root
                textAreaRef={textAreaRef}
                value={draft.value}
                onChange={draft.onChange}
                onSubmit={() =>
                    draft.submit(() => {
                        submitComposerForm()
                        return runInteractionLogic(logicProps).values.composerForm.draft
                    })
                }
                loading={isSubmitting}
                stopLoading={!!cancellationState}
                isTurnActive={isBusy}
                onStop={requestCancellation}
            >
                {draftRecovery && composerForm.draft && (
                    <Composer.Banner>
                        <p className="text-xs text-muted px-2 mb-2" data-attr="task-draft-restored">
                            {draftRecovery === 'unconfirmed'
                                ? "Delivery wasn't confirmed. Check the conversation before sending again."
                                : 'Draft restored. Review it before sending.'}
                        </p>
                    </Composer.Banner>
                )}
                {queuedMessages.length > 0 && (
                    <Composer.Banner>
                        <QueuedMessageList
                            messages={queuedMessages}
                            onUpdate={updateQueuedMessage}
                            onRemove={removeQueuedMessage}
                            onSteer={steerQueue}
                            steerDisabledReason={!canSend && !isSubmitting ? 'Wait for the agent to start' : undefined}
                            steerPending={steerPending || isSubmitting || !!cancellationState}
                        />
                    </Composer.Banner>
                )}
                <Composer.Frame>
                    <Composer.Header>
                        <AttachedContextBar />
                    </Composer.Header>
                    <Composer.Field>
                        <Composer.Placeholder>
                            {isTerminal ? 'Send a message to start a new run…' : 'Send a follow-up message…'}
                        </Composer.Placeholder>
                        <Composer.Textarea data-attr="sandbox-composer-input" autoFocus={autoFocus} />
                    </Composer.Field>
                    <Composer.Footer className="flex flex-wrap items-center gap-1 pl-2">
                        <fieldset
                            disabled={!controlsReady}
                            className="flex flex-wrap items-center gap-1 border-0 p-0 m-0 min-w-0"
                        >
                            {/* Mode + model/effort pickers: selection lives in the bound runInteractionLogic and is
                            applied when the message is sent — synced to the running agent on a follow-up,
                            or used to seed the next run once terminal. */}
                            <ComposerModePicker
                                selectedMode={selectedMode}
                                onModeChange={setMode}
                                modes={getModesForRuntimeAdapter(composerAdapter)}
                            />
                            <ComposerModelEffortPickers
                                models={catalogue}
                                selectedModel={selectedModel}
                                defaultModel={defaultModel}
                                isDefaultModelLoading={myConfigLoading}
                                selectedEffort={selectedEffort}
                                onModelChange={setModel}
                                onEffortChange={setEffort}
                                // While the run is live its harness is fixed to whatever the sandbox booted; once
                                // terminal the next send starts a fresh run, which may pick any harness.
                                lockedRuntimeAdapter={isTerminal ? null : logicProps.currentRuntimeAdapter}
                                onOpenDefaultSettings={() =>
                                    router.actions.push(
                                        urls.settings('environment-task-agents', 'task-agent-my-preference')
                                    )
                                }
                            />
                        </fieldset>
                        <div className="ml-auto">
                            <ContextUsageChip />
                        </div>
                    </Composer.Footer>
                </Composer.Frame>
                <AIConsentPopoverWrapper
                    placement="top-end"
                    showArrow
                    ignoreDismissal
                    hidden={!consentBlocked}
                    onApprove={submitAfterConsent}
                    onDismiss={() => clearConsentBlock()}
                >
                    <Composer.Submit data-attr="sandbox-composer-send" />
                </AIConsentPopoverWrapper>
            </Composer.Root>
        </div>
    )
}
