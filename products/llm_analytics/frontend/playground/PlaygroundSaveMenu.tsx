import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import React from 'react'

import { IconLlmPromptManagement } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { llmPlaygroundModelLogic } from './llmPlaygroundModelLogic'
import { getLinkedEvaluationLabel, llmPlaygroundPromptsLogic, type PromptConfig } from './llmPlaygroundPromptsLogic'

export function PlaygroundSaveMenu({
    promptId,
    prompt,
}: {
    promptId: string
    prompt: PromptConfig
}): JSX.Element | null {
    const { effectiveModelOptions } = useValues(llmPlaygroundModelLogic)
    const { linkedSource, saving } = useValues(llmPlaygroundPromptsLogic)
    const { clearLinkedSource, saveToLinkedPrompt, saveToLinkedEvaluation, saveAsNewPrompt, saveAsNewEvaluation } =
        useActions(llmPlaygroundPromptsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { searchParams } = useValues(router)

    const selectedModel = effectiveModelOptions.find((model) => model.id === prompt.model)
    const isEarlyAdopter = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
    const isPromptManagementEnabled = !!featureFlags[FEATURE_FLAGS.PROMPT_MANAGEMENT] || isEarlyAdopter
    const isEvaluationsEnabled = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS]

    const {
        promptId: linkedPromptId,
        promptName: linkedPromptName,
        evaluationId: linkedEvaluationId,
        evaluationName: linkedEvaluationName,
    } = linkedSource
    const hasLinkedSource = !!linkedPromptId || !!linkedEvaluationId

    const linkedPromptLabel = linkedPromptName ?? 'linked prompt'
    const linkedEvaluationLabel = getLinkedEvaluationLabel(linkedEvaluationName, linkedEvaluationId)

    const { source_prompt_id: _, source_evaluation_id: __, ...cleanSearchParams } = searchParams

    const modelConfig = selectedModel
        ? {
              model: prompt.model,
              provider: selectedModel.provider?.toLowerCase() ?? '',
              provider_key_id: prompt.selectedProviderKeyId ?? null,
          }
        : null

    const openSaveAsNewPromptDialog = (): void => {
        LemonDialog.openForm({
            title: 'Save as new prompt',
            initialValues: { name: '' },
            content: (
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="Enter a name for this prompt" autoFocus />
                </LemonField>
            ),
            errors: { name: (name) => (!name ? 'A name is required' : undefined) },
            onSubmit: ({ name }) => saveAsNewPrompt(name),
        })
    }

    const openSaveAsNewEvaluationDialog = (): void => {
        LemonDialog.openForm({
            title: 'Save as new evaluation',
            initialValues: { name: '' },
            content: (
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="Enter a name for this evaluation" autoFocus />
                </LemonField>
            ),
            errors: { name: (name) => (!name ? 'A name is required' : undefined) },
            onSubmit: ({ name }) => saveAsNewEvaluation(name, modelConfig),
        })
    }

    const confirmSaveToLinkedPrompt = (): void => {
        if (!linkedPromptId) {
            return
        }
        LemonDialog.open({
            title: `Save to prompt "${linkedPromptLabel}"?`,
            description: 'This will overwrite the current prompt with the system prompt from the playground.',
            primaryButton: { children: 'Save', type: 'primary', onClick: () => saveToLinkedPrompt() },
            secondaryButton: { children: 'Cancel', type: 'secondary' },
        })
    }

    const confirmSaveToLinkedEvaluation = (): void => {
        if (!linkedEvaluationId) {
            return
        }
        LemonDialog.open({
            title: `Save to ${linkedEvaluationLabel}?`,
            description:
                'This will overwrite the evaluation prompt and model configuration with the current playground state.',
            primaryButton: {
                children: 'Save',
                type: 'primary',
                onClick: () => saveToLinkedEvaluation(modelConfig),
            },
            secondaryButton: { children: 'Cancel', type: 'secondary' },
        })
    }

    const clearLinkedSourceState = (): void => {
        clearLinkedSource(promptId)
        router.actions.replace(combineUrl(urls.llmAnalyticsPlayground(), cleanSearchParams).url)
    }

    const linkedActions: JSX.Element[] = []
    const saveAsNewActions: JSX.Element[] = []
    const loadActions: JSX.Element[] = []

    if (linkedPromptId && linkedPromptName && isPromptManagementEnabled) {
        linkedActions.push(
            <LemonButton
                key="save-linked-prompt"
                type="tertiary"
                size="small"
                fullWidth
                className="justify-start"
                onClick={confirmSaveToLinkedPrompt}
            >
                <span
                    className="block w-full whitespace-normal break-all text-left"
                    title={`Save to prompt "${linkedPromptLabel}"`}
                >
                    Save to prompt "{linkedPromptLabel}"
                </span>
            </LemonButton>
        )
    }

    if (linkedEvaluationId && isEvaluationsEnabled) {
        linkedActions.push(
            <LemonButton
                key="save-linked-evaluation"
                type="tertiary"
                size="small"
                fullWidth
                className="justify-start"
                onClick={confirmSaveToLinkedEvaluation}
            >
                <span
                    className="block w-full whitespace-normal break-all text-left"
                    title={`Save to ${linkedEvaluationLabel}`}
                >
                    Save to {linkedEvaluationLabel}
                </span>
            </LemonButton>
        )
    }

    if (hasLinkedSource) {
        linkedActions.push(
            <LemonButton key="unlink-source" type="tertiary" size="small" fullWidth onClick={clearLinkedSourceState}>
                Unlink from source
            </LemonButton>
        )
    }

    if (isPromptManagementEnabled) {
        saveAsNewActions.push(
            <LemonButton
                key="save-new-prompt"
                type="tertiary"
                size="small"
                fullWidth
                onClick={openSaveAsNewPromptDialog}
            >
                Save as new prompt
            </LemonButton>
        )
        loadActions.push(
            <LemonButton
                key="load-prompt"
                type="tertiary"
                size="small"
                fullWidth
                onClick={() => router.actions.push(urls.llmAnalyticsPrompts())}
            >
                Load prompt
            </LemonButton>
        )
    }

    if (isEvaluationsEnabled) {
        saveAsNewActions.push(
            <LemonButton
                key="save-new-evaluation"
                type="tertiary"
                size="small"
                fullWidth
                onClick={openSaveAsNewEvaluationDialog}
            >
                Save as new evaluation
            </LemonButton>
        )
        loadActions.push(
            <LemonButton
                key="load-evaluation"
                type="tertiary"
                size="small"
                fullWidth
                onClick={() => router.actions.push(urls.llmAnalyticsEvaluations())}
            >
                Load evaluation
            </LemonButton>
        )
    }

    const menuGroups = [linkedActions, saveAsNewActions, loadActions].filter((group) => group.length > 0)
    if (menuGroups.length === 0) {
        return null
    }

    return (
        <LemonDropdown
            overlay={
                <div className={`${hasLinkedSource ? 'w-72' : 'w-56'} p-1`}>
                    {menuGroups.map((group, groupIndex) => (
                        <React.Fragment key={`group-${groupIndex}`}>
                            {groupIndex > 0 ? <LemonDivider className="my-1" /> : null}
                            {group}
                        </React.Fragment>
                    ))}
                </div>
            }
            placement="bottom-end"
        >
            <LemonButton
                size="small"
                icon={<IconLlmPromptManagement className="text-warning" />}
                tooltip={
                    hasLinkedSource
                        ? 'Save changes back to the linked item or create a new one'
                        : 'Save this system prompt as a prompt or evaluation'
                }
                noPadding
                loading={saving}
                data-attr="llma-playground-save-system-prompt"
            />
        </LemonDropdown>
    )
}
