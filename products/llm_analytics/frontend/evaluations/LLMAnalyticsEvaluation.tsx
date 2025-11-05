import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { urls } from '~/scenes/urls'

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
    } = useValues(llmEvaluationLogic)
    const { setEvaluationName, setEvaluationDescription, setEvaluationEnabled, saveEvaluation, resetEvaluation } =
        useActions(llmEvaluationLogic)
    const { push } = useActions(router)

    if (evaluationLoading) {
        return <LemonSkeleton className="w-full h-96" />
    }

    if (!evaluation) {
        return <NotFound object="evaluation" />
    }

    const handleSave = (): void => {
        saveEvaluation()
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
                        disabled={!formValid}
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
                        </div>
                    </div>

                    {/* Prompt Configuration */}
                    <div className="bg-bg-light border rounded p-6">
                        <h3 className="text-lg font-semibold mb-4">Evaluation prompt</h3>
                        <EvaluationPromptEditor />
                    </div>

                    {/* Trigger Configuration */}
                    <div className="bg-bg-light border rounded p-6">
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
    paramsToProps: ({ params: { id } }) => ({
        evaluationId: id && id !== 'new' ? id : 'new',
    }),
}
