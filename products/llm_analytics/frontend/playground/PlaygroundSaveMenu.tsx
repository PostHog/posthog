import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'
import React from 'react'

import { IconLlmPromptManagement } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { llmPlaygroundModelLogic } from './llmPlaygroundModelLogic'
import {
    cleanSourceSearchParams,
    getLinkedSourceLabel,
    llmPlaygroundPromptsLogic,
    type PromptConfig,
} from './llmPlaygroundPromptsLogic'

export function PlaygroundSaveMenu({ prompt }: { prompt: PromptConfig }): JSX.Element | null {
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

    const { promptName: linkedPromptName, evaluationId: linkedEvaluationId } = linkedSource
    const hasLinkedSource = !!linkedPromptName || !!linkedEvaluationId
    const linkedLabel = getLinkedSourceLabel(linkedSource)

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
            onSubmit: ({ name }) => saveAsNewPrompt(prompt.id, name),
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
            onSubmit: ({ name }) => saveAsNewEvaluation(prompt.id, name, modelConfig),
        })
    }

    const confirmSaveToLinkedSource = (): void => {
        if (!linkedLabel) {
            return
        }
        const isPrompt = linkedSource.type === 'prompt'
        LemonDialog.open({
            title: `Save to ${linkedLabel}?`,
            description: isPrompt
                ? 'This will publish a new version of the prompt with the system prompt from the playground.'
                : 'This will update the evaluation prompt and model configuration with the current playground state.',
            primaryButton: {
                children: isPrompt ? 'Publish version' : 'Save',
                type: 'primary',
                onClick: () =>
                    isPrompt ? saveToLinkedPrompt(prompt.id) : saveToLinkedEvaluation(prompt.id, modelConfig),
            },
            secondaryButton: { children: 'Cancel', type: 'secondary' },
        })
    }

    const clearLinkedSourceState = (): void => {
        posthog.capture('llma playground source unlinked')
        clearLinkedSource()
        router.actions.replace(combineUrl(urls.llmAnalyticsPlayground(), cleanSourceSearchParams(searchParams)).url)
    }

    const linkedActions: JSX.Element[] = []
    const saveAsNewActions: JSX.Element[] = []
    const loadActions: JSX.Element[] = []

    const isLinkedSourceEnabled =
        (linkedSource.type === 'prompt' && linkedPromptName && isPromptManagementEnabled) ||
        (linkedSource.type === 'evaluation' && linkedEvaluationId && isEvaluationsEnabled && modelConfig)

    if (linkedLabel && isLinkedSourceEnabled) {
        linkedActions.push(
            <LemonButton
                key="save-linked-source"
                type="tertiary"
                size="small"
                fullWidth
                className="justify-start"
                onClick={confirmSaveToLinkedSource}
            >
                <span className="block w-full whitespace-normal break-all text-left" title={`Save to ${linkedLabel}`}>
                    Save to {linkedLabel}
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
            <LemonButton key="load-prompt" type="tertiary" size="small" fullWidth to={urls.llmAnalyticsPrompts()}>
                Load prompt
            </LemonButton>
        )
    }

    if (isEvaluationsEnabled && modelConfig) {
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
                to={urls.llmAnalyticsEvaluations()}
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
