import { useEffect, useState } from 'react'

import { LemonButton, LemonModal, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'

import { EvaluationTemplateChoice, EvaluationTemplatePicker } from '../evaluations/EvaluationTemplates'
import { defaultEvaluationTemplates, LLMJudgeTemplate } from '../evaluations/templates'
import {
    CLUSTER_EVALUATION_PROMPT_MAX_LENGTH,
    buildClusterEvaluationGoal,
    buildClusterEvaluationPrompt,
    buildClusterTemplateEvaluationPrompt,
} from './clusterEvaluationPrompt'
import { Cluster } from './types'

const clusterEvaluationTemplates = defaultEvaluationTemplates.filter(
    (template): template is LLMJudgeTemplate => template.evaluation_type === 'llm_judge'
)

interface ClusterEvaluationModalProps {
    cluster: Cluster | null
    isOpen: boolean
    creating: boolean
    onClose: () => void
    onCreate: (cluster: Cluster, evaluationGoal: string, evaluationPrompt: string) => void
}

export function ClusterEvaluationModal({
    cluster,
    isOpen,
    creating,
    onClose,
    onCreate,
}: ClusterEvaluationModalProps): JSX.Element | null {
    const [evaluationGoal, setEvaluationGoal] = useState('')
    const [evaluationPrompt, setEvaluationPrompt] = useState('')
    const [promptEdited, setPromptEdited] = useState(false)
    const [selectedTemplate, setSelectedTemplate] = useState<EvaluationTemplateChoice | null>(null)

    useEffect(() => {
        if (!cluster || !isOpen) {
            return
        }

        setSelectedTemplate(null)
        setEvaluationGoal('')
        setEvaluationPrompt('')
        setPromptEdited(false)
    }, [cluster, isOpen])

    if (!cluster) {
        return null
    }

    const clusterTitle = cluster.title || `Cluster ${cluster.cluster_id}`
    const selectedTemplateName = selectedTemplate === 'blank' ? 'Create from scratch' : selectedTemplate?.name

    const buildPromptForTemplate = (
        template: EvaluationTemplateChoice,
        cluster: Cluster,
        nextEvaluationGoal: string
    ): string => {
        if (template === 'blank') {
            return buildClusterEvaluationPrompt(cluster, nextEvaluationGoal)
        }

        return buildClusterTemplateEvaluationPrompt(template as LLMJudgeTemplate, cluster, nextEvaluationGoal)
    }

    const selectTemplate = (template: EvaluationTemplateChoice): void => {
        const nextEvaluationGoal = template === 'blank' ? buildClusterEvaluationGoal(cluster) : ''

        setSelectedTemplate(template)
        setEvaluationGoal(nextEvaluationGoal)
        setEvaluationPrompt(buildPromptForTemplate(template, cluster, nextEvaluationGoal))
        setPromptEdited(false)
    }

    const updateGoal = (value: string): void => {
        setEvaluationGoal(value)
        if (!promptEdited && selectedTemplate) {
            setEvaluationPrompt(buildPromptForTemplate(selectedTemplate, cluster, value))
        }
    }

    const promptDisabledReason = !selectedTemplate
        ? 'Choose an evaluation template'
        : !evaluationPrompt.trim()
          ? 'Evaluation prompt is required'
          : evaluationPrompt.length > CLUSTER_EVALUATION_PROMPT_MAX_LENGTH
            ? `Evaluation prompt must be ${CLUSTER_EVALUATION_PROMPT_MAX_LENGTH} characters or fewer`
            : undefined

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            simple
            maxWidth={selectedTemplate ? '44rem' : '68rem'}
            className="w-full"
            data-attr="clusters-create-evaluation-modal"
        >
            {!selectedTemplate ? (
                <LemonModalContent className="max-h-[80vh] overflow-y-auto">
                    <EvaluationTemplatePicker
                        title={`Create evaluation from "${clusterTitle}"`}
                        description="Choose a template. We'll use this cluster's summary to draft the evaluation."
                        minHeight="auto"
                        templates={clusterEvaluationTemplates}
                        blankDescription="Build a custom LLM judge evaluation from this cluster"
                        onSelectTemplate={selectTemplate}
                    />
                </LemonModalContent>
            ) : (
                <>
                    <LemonModalHeader>Create draft evaluation</LemonModalHeader>
                    <LemonModalContent className="space-y-4 max-h-[70vh] overflow-y-auto pr-1">
                        <div className="rounded border bg-surface-secondary p-3 space-y-2">
                            <div className="flex items-center gap-2 flex-wrap">
                                <div className="font-semibold">Template</div>
                                <LemonTag type={selectedTemplate === 'blank' ? 'muted' : 'caution'}>
                                    {selectedTemplateName}
                                </LemonTag>
                            </div>
                            <div className="text-sm text-muted">
                                {selectedTemplate === 'blank'
                                    ? 'Draft a boolean LLM-as-judge evaluation from this cluster.'
                                    : 'The selected template prompt is preserved, with cluster context appended at the bottom.'}
                            </div>
                        </div>

                        <div className="space-y-2">
                            <div className="text-sm font-medium">
                                {selectedTemplate === 'blank'
                                    ? 'What should this evaluation detect?'
                                    : 'Additional context'}
                            </div>
                            <LemonTextArea
                                value={evaluationGoal}
                                onChange={updateGoal}
                                rows={3}
                                maxLength={1000}
                                placeholder={
                                    selectedTemplate === 'blank'
                                        ? 'Detect whether the user is struggling with event tracking setup or debugging.'
                                        : 'Optional. Add anything specific you want this template to pay attention to.'
                                }
                                data-attr="clusters-create-evaluation-goal"
                            />
                            <div className="text-xs text-muted">
                                {selectedTemplate === 'blank'
                                    ? 'This becomes the positive case for a boolean LLM-as-judge evaluation.'
                                    : 'This is added inside the cluster context section at the bottom of the prompt.'}
                            </div>
                        </div>

                        <div className="space-y-2">
                            <div className="flex items-center justify-between gap-2">
                                <div className="text-sm font-medium">Evaluation prompt</div>
                                <div className="text-xs text-muted">
                                    {evaluationPrompt.length}/{CLUSTER_EVALUATION_PROMPT_MAX_LENGTH}
                                </div>
                            </div>
                            <LemonTextArea
                                value={evaluationPrompt}
                                onChange={(value) => {
                                    setEvaluationPrompt(value)
                                    setPromptEdited(true)
                                }}
                                rows={7}
                                maxLength={CLUSTER_EVALUATION_PROMPT_MAX_LENGTH}
                                className="font-mono text-sm"
                                data-attr="clusters-create-evaluation-prompt"
                            />
                            <div className="text-xs text-muted">
                                The draft evaluation stays disabled, so you can review it again before enabling.
                            </div>
                        </div>
                    </LemonModalContent>
                    <LemonModalFooter>
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                setSelectedTemplate(null)
                                setEvaluationGoal('')
                                setEvaluationPrompt('')
                                setPromptEdited(false)
                            }}
                            disabled={creating}
                            data-attr="clusters-create-evaluation-back"
                        >
                            Back
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            onClick={onClose}
                            disabled={creating}
                            data-attr="clusters-create-evaluation-cancel"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => onCreate(cluster, evaluationGoal, evaluationPrompt)}
                            loading={creating}
                            disabledReason={promptDisabledReason}
                            data-attr="clusters-create-evaluation-submit"
                        >
                            Create draft evaluation
                        </LemonButton>
                    </LemonModalFooter>
                </>
            )}
        </LemonModal>
    )
}
