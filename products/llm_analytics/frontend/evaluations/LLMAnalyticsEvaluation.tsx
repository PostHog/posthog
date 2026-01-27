import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'
import { useRef } from 'react'

import { IconArrowLeft, IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { urls } from '~/scenes/urls'

import { LLMProvider, LLM_PROVIDER_LABELS } from '../settings/llmProviderKeysLogic'
import { EvaluationPromptEditor } from './components/EvaluationPromptEditor'
import { EvaluationRunsTable } from './components/EvaluationRunsTable'
import { EvaluationTriggers } from './components/EvaluationTriggers'
import { LLMEvaluationLogicProps, llmEvaluationLogic } from './llmEvaluationLogic'

export function LLMAnalyticsEvaluation(): JSX.Element {
    const {
        evaluation,
        evaluationLoading,
        evaluationFormSubmitting,
        hasUnsavedChanges,
        formValid,
        isNewEvaluation,
        runsSummary,
        selectedProvider,
        selectedKeyId,
        selectedModel,
        keysForSelectedProvider,
        availableModels,
        availableModelsLoading,
        providerKeysLoading,
    } = useValues(llmEvaluationLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        setEvaluationName,
        setEvaluationDescription,
        setEvaluationEnabled,
        setAllowsNA,
        saveEvaluation,
        resetEvaluation,
        setSelectedProvider,
        setSelectedKeyId,
        setSelectedModel,
    } = useActions(llmEvaluationLogic)
    const { push } = useActions(router)
    const triggersRef = useRef<HTMLDivElement>(null)

    if (evaluationLoading) {
        return <LemonSkeleton className="w-full h-96" />
    }

    if (!evaluation) {
        return <NotFound object="evaluation" />
    }

    const basicFieldsValid = evaluation.name.length > 0 && evaluation.evaluation_config.prompt.length > 0
    const percentageUnset = evaluation.conditions.some((c) => c.rollout_percentage === 0)
    const saveButtonDisabled = !basicFieldsValid

    const handleSave = (): void => {
        // If percentage is unset but other fields are valid, scroll to triggers
        if (basicFieldsValid && percentageUnset) {
            triggersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
            return
        }

        // Otherwise proceed with save if form is valid
        if (formValid) {
            saveEvaluation()
        }
    }

    const handleCancel = (): void => {
        if (hasUnsavedChanges) {
            resetEvaluation()
        }
        push(urls.llmAnalyticsEvaluations())
    }

    return (
        <div className="space-y-6">
            <SceneBreadcrumbBackButton />
            {/* Header */}
            <div className="flex justify-between items-start pb-4 border-b">
                <div className="space-y-2">
                    <h1 className="text-2xl font-semibold">{isNewEvaluation ? 'New evaluation' : evaluation.name}</h1>
                    <div className="flex items-center gap-2">
                        {isNewEvaluation ? (
                            <LemonTag type="primary">New</LemonTag>
                        ) : (
                            <>
                                <LemonTag type={evaluation.enabled ? 'success' : 'default'}>
                                    {evaluation.enabled ? 'Enabled' : 'Disabled'}
                                </LemonTag>
                                {hasUnsavedChanges && <LemonTag type="warning">Unsaved Changes</LemonTag>}
                            </>
                        )}
                    </div>
                </div>
                <div className="flex gap-2">
                    <LemonButton type="secondary" icon={<IconArrowLeft />} onClick={handleCancel}>
                        {hasUnsavedChanges ? 'Cancel' : 'Back'}
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSave}
                        disabled={saveButtonDisabled}
                        loading={evaluationFormSubmitting}
                    >
                        {isNewEvaluation ? 'Create Evaluation' : 'Save Changes'}
                    </LemonButton>
                </div>
            </div>

            {/* Configuration Form */}
            <div className="max-w-4xl">
                <Form logic={llmEvaluationLogic} formKey="evaluation" className="space-y-6">
                    {/* Basic Information */}
                    <div className="bg-bg-light border rounded p-6">
                        <h3 className="text-lg font-semibold mb-4">Basic information</h3>

                        <div className="space-y-4">
                            <Field name="name" label="Name">
                                <LemonInput
                                    value={evaluation.name}
                                    onChange={setEvaluationName}
                                    placeholder="e.g., Helpfulness Check"
                                    maxLength={100}
                                />
                            </Field>

                            <Field name="description" label="Description (optional)">
                                <LemonTextArea
                                    value={evaluation.description || ''}
                                    onChange={setEvaluationDescription}
                                    placeholder="Describe what this evaluation checks for..."
                                    rows={2}
                                    maxLength={500}
                                />
                            </Field>

                            <Field name="enabled" label="Status">
                                <div className="flex items-center gap-2">
                                    <LemonSwitch checked={evaluation.enabled} onChange={setEvaluationEnabled} />
                                    <span>{evaluation.enabled ? 'Enabled' : 'Disabled'}</span>
                                    <span className="text-muted text-sm">
                                        {evaluation.enabled
                                            ? 'This evaluation will run automatically based on triggers'
                                            : 'This evaluation is paused and will not run'}
                                    </span>
                                </div>
                            </Field>

                            <Field
                                name="allows_na"
                                label={
                                    <div className="flex items-center gap-1">
                                        <span>Allow N/A responses</span>
                                        <Tooltip title="Sometimes forcing a True or False is not enough and you want the LLM to decide if the eval is applicable or not. Enable this when the evaluation criteria may not apply to all generations.">
                                            <IconInfo className="text-muted text-base" />
                                        </Tooltip>
                                    </div>
                                }
                            >
                                <div className="flex items-center gap-2">
                                    <LemonSwitch
                                        checked={evaluation.output_config.allows_na ?? false}
                                        onChange={setAllowsNA}
                                    />
                                    <span className="text-muted text-sm">
                                        {evaluation.output_config.allows_na
                                            ? 'Evaluation can return "Not Applicable" when criteria doesn\'t apply'
                                            : 'Evaluation returns true or false'}
                                    </span>
                                </div>
                            </Field>
                        </div>
                    </div>

                    {/* Prompt Configuration */}
                    <div className="bg-bg-light border rounded p-6">
                        <h3 className="text-lg font-semibold mb-4">Evaluation prompt</h3>
                        <EvaluationPromptEditor />
                    </div>

                    {/* Judge Model Configuration */}
                    {featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_CUSTOM_MODELS] && (
                        <div className="bg-bg-light border rounded p-6">
                            <h3 className="text-lg font-semibold mb-2">Judge model</h3>
                            <p className="text-muted text-sm mb-4">
                                Select which LLM provider and model to use for running this evaluation.
                            </p>

                            <div className="space-y-4">
                                <Field name="provider" label="Provider">
                                    <LemonSelect
                                        value={selectedProvider}
                                        onChange={(value) => setSelectedProvider(value as LLMProvider)}
                                        options={[
                                            { value: 'openai', label: LLM_PROVIDER_LABELS.openai },
                                            { value: 'anthropic', label: LLM_PROVIDER_LABELS.anthropic },
                                            { value: 'gemini', label: LLM_PROVIDER_LABELS.gemini },
                                        ]}
                                        fullWidth
                                    />
                                </Field>

                                <Field
                                    name="provider_key"
                                    label={
                                        <div className="flex items-center gap-1">
                                            <span>API key</span>
                                            <span className="text-muted">-</span>
                                            <Link to={urls.llmAnalyticsSettings()}>Manage</Link>
                                        </div>
                                    }
                                >
                                    <LemonSelect
                                        value={selectedKeyId || 'posthog_default'}
                                        onChange={(value) =>
                                            setSelectedKeyId(value === 'posthog_default' ? null : value)
                                        }
                                        options={[
                                            ...(keysForSelectedProvider.length === 0
                                                ? [{ value: 'posthog_default', label: 'PostHog default' }]
                                                : []),
                                            ...keysForSelectedProvider.map((key) => ({
                                                value: key.id,
                                                label: key.name,
                                            })),
                                        ]}
                                        loading={providerKeysLoading}
                                        fullWidth
                                    />
                                </Field>

                                <Field name="model" label="Model">
                                    <>
                                        <LemonSelect
                                            value={selectedModel || undefined}
                                            onChange={(value) => setSelectedModel(value || '')}
                                            options={availableModels.map((model) => ({
                                                value: model.id,
                                                label: model.id,
                                                disabledReason:
                                                    !selectedKeyId && !model.posthog_available
                                                        ? 'Requires API key'
                                                        : undefined,
                                            }))}
                                            loading={availableModelsLoading}
                                            placeholder="Select a model"
                                            fullWidth
                                            disabled={!selectedKeyId}
                                        />
                                        {!selectedKeyId && (
                                            <p className="text-xs text-muted mt-1">
                                                Add your own API key for model selection
                                            </p>
                                        )}
                                    </>
                                </Field>
                            </div>
                        </div>
                    )}

                    {/* Trigger Configuration */}
                    <div ref={triggersRef} className="bg-bg-light border rounded p-6">
                        <h3 className="text-lg font-semibold mb-4">Triggers</h3>
                        <p className="text-muted text-sm mb-4">
                            Configure when this evaluation should run on your LLM generations.
                        </p>
                        <EvaluationTriggers />
                    </div>
                </Form>
            </div>

            {/* Evaluation Runs (only for existing evaluations) */}
            {!isNewEvaluation && (
                <>
                    <LemonDivider />
                    <div className="max-w-6xl">
                        <div className="flex justify-between items-center mb-4">
                            <div>
                                <h3 className="text-lg font-semibold">Evaluation runs</h3>
                                <p className="text-muted text-sm">History of when this evaluation has been executed.</p>
                            </div>
                            {runsSummary && (
                                <div className="flex gap-4 text-sm">
                                    <div className="text-center">
                                        <div className="font-semibold text-lg">{runsSummary.total}</div>
                                        <div className="text-muted">Total Runs</div>
                                    </div>
                                    <div className="text-center">
                                        <div className="font-semibold text-lg text-success">
                                            {runsSummary.successRate}%
                                        </div>
                                        <div className="text-muted">Success Rate</div>
                                    </div>
                                    {evaluation.output_config.allows_na && (
                                        <div className="text-center">
                                            <div className="font-semibold text-lg">
                                                {runsSummary.applicabilityRate}%
                                            </div>
                                            <div className="text-muted">Applicable</div>
                                        </div>
                                    )}
                                    <div className="text-center">
                                        <div className="font-semibold text-lg text-danger">{runsSummary.errors}</div>
                                        <div className="text-muted">Errors</div>
                                    </div>
                                </div>
                            )}
                        </div>
                        <EvaluationRunsTable />
                    </div>
                </>
            )}
        </div>
    )
}

export const scene: SceneExport<LLMEvaluationLogicProps> = {
    component: LLMAnalyticsEvaluation,
    logic: llmEvaluationLogic,
    paramsToProps: ({ params: { id }, searchParams }) => ({
        evaluationId: id && id !== 'new' ? id : 'new',
        templateKey: typeof searchParams.template === 'string' ? searchParams.template : undefined,
    }),
}
