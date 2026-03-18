import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'
import { useRef } from 'react'

import { IconArrowLeft, IconInfo, IconPlay } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTabs,
    LemonTag,
    LemonTextArea,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { urls } from '~/scenes/urls'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { getModelPickerFooterLink, ModelPicker } from '../ModelPicker'
import { modelPickerLogic } from '../modelPickerLogic'
import { providerKeyStateIssueDescription, providerLabel } from '../settings/providerKeyStateUtils'
import { EvaluationCodeEditor } from './components/EvaluationCodeEditor'
import { EvaluationPromptEditor } from './components/EvaluationPromptEditor'
import { EvaluationRunsTable } from './components/EvaluationRunsTable'
import { EvaluationTriggers } from './components/EvaluationTriggers'
import { LLMEvaluationLogicProps, llmEvaluationLogic } from './llmEvaluationLogic'
import { EvaluationType } from './types'

export function LLMAnalyticsEvaluation(): JSX.Element {
    const {
        evaluation,
        evaluationLoading,
        evaluationFormSubmitting,
        hasUnsavedChanges,
        formValid,
        isNewEvaluation,
        runsSummary,
        evaluationProviderKeyIssue,
        signalEmissionEnabled,
        activeTab,
    } = useValues(llmEvaluationLogic)
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { searchParams } = useValues(router)
    const {
        setEvaluationName,
        setEvaluationDescription,
        setEvaluationEnabled,
        setAllowsNA,
        saveEvaluation,
        resetEvaluation,
        setEvaluationType,
        setSignalEmission,
        setActiveTab,
    } = useActions(llmEvaluationLogic)
    const { push } = useActions(router)
    const triggersRef = useRef<HTMLDivElement>(null)
    const settingsUrl = combineUrl(urls.llmAnalyticsEvaluations(), { ...searchParams, tab: 'settings' }).url

    if (evaluationLoading) {
        return <LemonSkeleton className="w-full h-96" />
    }

    if (!evaluation) {
        return <NotFound object="evaluation" />
    }
    const openInPlaygroundUrl =
        evaluation.evaluation_type === 'llm_judge' && evaluation.id
            ? combineUrl(urls.llmAnalyticsPlayground(), { source_evaluation_id: evaluation.id }).url
            : null

    const isHog = evaluation.evaluation_type === 'hog'
    const configValid = isHog
        ? evaluation.evaluation_config.source.trim().length > 0
        : evaluation.evaluation_config.prompt.trim().length > 0
    const basicFieldsValid = evaluation.name.length > 0 && configValid
    const percentageUnset = evaluation.conditions.some((c) => c.rollout_percentage === 0)
    const saveButtonDisabled = !basicFieldsValid

    const handleSave = (): void => {
        // If percentage is unset but other fields are valid, switch to settings and scroll to triggers
        if (basicFieldsValid && percentageUnset) {
            setActiveTab('configuration')
            requestAnimationFrame(() => {
                triggersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
            })
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
        push(combineUrl(urls.llmAnalyticsEvaluations(), searchParams).url)
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
                                {hasUnsavedChanges && <LemonTag type="warning">Unsaved changes</LemonTag>}
                            </>
                        )}
                    </div>
                </div>
                <div className="flex gap-2">
                    {openInPlaygroundUrl ? (
                        <LemonButton
                            type="secondary"
                            icon={<IconPlay />}
                            to={openInPlaygroundUrl}
                            data-attr="llma-playground-open-from-evaluation"
                        >
                            Open in Playground
                        </LemonButton>
                    ) : null}
                    <LemonButton type="secondary" icon={<IconArrowLeft />} onClick={handleCancel}>
                        {hasUnsavedChanges ? 'Cancel' : 'Back'}
                    </LemonButton>
                    {activeTab !== 'runs' && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                onClick={handleSave}
                                disabled={saveButtonDisabled}
                                loading={evaluationFormSubmitting}
                            >
                                {isNewEvaluation ? 'Create evaluation' : 'Save changes'}
                            </LemonButton>
                        </AccessControlAction>
                    )}
                </div>
            </div>

            {evaluationProviderKeyIssue && (
                <LemonBanner type="warning">
                    <div className="space-y-2">
                        <p>
                            This evaluation uses API key{' '}
                            <span className="font-semibold">{evaluationProviderKeyIssue.name}</span> (
                            {providerLabel(evaluationProviderKeyIssue.provider)}){' '}
                            {providerKeyStateIssueDescription(evaluationProviderKeyIssue.state)}.
                        </p>
                        <p>Error: {evaluationProviderKeyIssue.error_message || 'Unknown error'}</p>
                        <Link to={settingsUrl}>Go to settings to fix this key.</Link>
                    </div>
                </LemonBanner>
            )}

            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key)}
                data-attr="llma-evaluation-tabs"
                tabs={[
                    !isNewEvaluation && {
                        key: 'runs',
                        label: 'Runs',
                        'data-attr': 'llma-evaluation-runs-tab',
                        content: (
                            <div className="max-w-6xl">
                                <div className="flex justify-between items-center mb-4">
                                    <p className="text-muted text-sm m-0">
                                        History of when this evaluation has been executed.
                                    </p>
                                    {runsSummary && (
                                        <div className="flex gap-4 text-sm">
                                            <div className="text-center">
                                                <div className="font-semibold text-lg">{runsSummary.total}</div>
                                                <div className="text-muted">Total runs</div>
                                            </div>
                                            <div className="text-center">
                                                <div className="font-semibold text-lg text-success">
                                                    {runsSummary.successRate}%
                                                </div>
                                                <div className="text-muted">Success rate</div>
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
                                                <div className="font-semibold text-lg text-danger">
                                                    {runsSummary.errors}
                                                </div>
                                                <div className="text-muted">Errors</div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                                <EvaluationRunsTable />
                            </div>
                        ),
                    },
                    {
                        key: 'configuration',
                        label: 'Configuration',
                        'data-attr': 'llma-evaluation-configuration-tab',
                        content: (
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

                                            {featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_HOG_CODE] && (
                                                <Field name="evaluation_type" label="Method">
                                                    <LemonSelect
                                                        value={evaluation.evaluation_type}
                                                        onChange={(value) => setEvaluationType(value as EvaluationType)}
                                                        options={[
                                                            {
                                                                value: 'llm_judge',
                                                                label: 'LLM as a judge',
                                                            },
                                                            {
                                                                value: 'hog',
                                                                label: 'Hog code',
                                                            },
                                                        ]}
                                                        fullWidth
                                                    />
                                                </Field>
                                            )}
                                            <p className="text-muted text-sm -mt-2">
                                                {isHog ? (
                                                    <>
                                                        Run deterministic{' '}
                                                        <Link to="https://posthog.com/docs/hog" target="_blank">
                                                            Hog code
                                                        </Link>{' '}
                                                        against each generation. No LLM cost, instant results.
                                                    </>
                                                ) : (
                                                    'Use an LLM to evaluate each generation against a natural-language prompt.'
                                                )}
                                            </p>

                                            <Field name="description" label="Description (optional)">
                                                <LemonTextArea
                                                    value={evaluation.description || ''}
                                                    onChange={setEvaluationDescription}
                                                    placeholder="Describe what this evaluation checks for..."
                                                    rows={2}
                                                    maxLength={500}
                                                />
                                            </Field>

                                            <div className="flex items-center gap-2">
                                                <LemonSwitch
                                                    checked={evaluation.enabled}
                                                    onChange={setEvaluationEnabled}
                                                    label="Enable evaluation"
                                                />
                                                <span className="text-muted text-sm">
                                                    {evaluation.enabled
                                                        ? 'This evaluation will run automatically based on triggers'
                                                        : 'This evaluation is paused and will not run'}
                                                </span>
                                            </div>

                                            <Field
                                                name="allows_na"
                                                label={
                                                    <div className="flex items-center gap-1">
                                                        <span>Allow N/A responses</span>
                                                        <Tooltip
                                                            title={
                                                                isHog
                                                                    ? 'When enabled, returning null from your Hog code means "not applicable" instead of being treated as an error.'
                                                                    : 'Sometimes forcing a True or False is not enough and you want the LLM to decide if the evaluation is applicable or not. Enable this when the evaluation criteria may not apply to all generations.'
                                                            }
                                                        >
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
                                                            ? isHog
                                                                ? 'Returning null means "Not Applicable"'
                                                                : 'Evaluation can return "Not Applicable" when criteria doesn\'t apply'
                                                            : isHog
                                                              ? 'Evaluation must return true or false'
                                                              : 'Evaluation returns true or false'}
                                                    </span>
                                                </div>
                                            </Field>
                                            {!isNewEvaluation && user?.is_staff && (
                                                <div className="flex items-center gap-2">
                                                    <LemonSwitch
                                                        checked={signalEmissionEnabled}
                                                        onChange={setSignalEmission}
                                                    />
                                                    <span>Emit signals</span>
                                                    <Tooltip title="When enabled, true verdicts from this evaluation will be emitted as signals for clustering and investigation.">
                                                        <IconInfo className="text-muted text-base" />
                                                    </Tooltip>
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    {/* Prompt / Code Configuration */}
                                    <div className="bg-bg-light border rounded p-6">
                                        <h3 className="text-lg font-semibold mb-4">
                                            {isHog ? 'Evaluation code' : 'Evaluation prompt'}
                                        </h3>
                                        {isHog ? <EvaluationCodeEditor /> : <EvaluationPromptEditor />}
                                    </div>

                                    {/* Judge Model Configuration (LLM judge only) */}
                                    {!isHog && featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_CUSTOM_MODELS] && (
                                        <EvaluationModelPicker />
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
                        ),
                    },
                ]}
            />
        </div>
    )
}

function EvaluationModelPicker(): JSX.Element {
    const {
        hasByokKeys,
        byokModels,
        trialModels,
        providerModelGroups,
        trialProviderModelGroups,
        byokModelsLoading,
        trialModelsLoading,
        providerKeysLoading,
    } = useValues(modelPickerLogic)
    const { selectedModel, selectedPickerProviderKeyId } = useValues(llmEvaluationLogic)
    const { selectModelFromPicker } = useActions(llmEvaluationLogic)

    const allModels = hasByokKeys ? byokModels : trialModels
    const selectedModelName = allModels.find((m) => m.id === selectedModel)?.name
    const groups = hasByokKeys ? providerModelGroups : trialProviderModelGroups
    const loading = hasByokKeys ? byokModelsLoading || providerKeysLoading : trialModelsLoading

    const footerLink = getModelPickerFooterLink(hasByokKeys)

    return (
        <div className="bg-bg-light border rounded p-6">
            <h3 className="text-lg font-semibold mb-2">Judge model</h3>
            <p className="text-muted text-sm mb-4">
                Select which LLM provider and model to use for running this evaluation.
            </p>

            <div className="space-y-4">
                <Field name="model" label="Model">
                    <ModelPicker
                        model={selectedModel}
                        selectedProviderKeyId={selectedPickerProviderKeyId}
                        onSelect={selectModelFromPicker}
                        groups={groups}
                        loading={loading}
                        footerLink={footerLink}
                        selectedModelName={selectedModelName}
                        data-attr="evaluation-model-selector"
                    />
                </Field>
            </div>
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
