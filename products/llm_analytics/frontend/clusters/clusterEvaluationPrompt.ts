import { LLMJudgeTemplate } from '../evaluations/templates'
import { Cluster } from './types'

export const CLUSTER_EVALUATION_PROMPT_MAX_LENGTH = 2000

function clusterTitle(cluster: Cluster): string {
    return cluster.title?.trim() || `Cluster ${cluster.cluster_id}`
}

function clusterSummary(cluster: Cluster): string {
    return cluster.description?.trim() || 'No cluster summary was available.'
}

function buildClusterContextSection(cluster: Cluster, additionalContext?: string): string {
    const trimmedAdditionalContext = additionalContext?.trim()

    return `## Cluster context added from LLM Analytics
The context below was added because this draft evaluation was created from a cluster. Edit or remove it before creating the draft if it does not match what you want to detect.

Source cluster: ${clusterTitle(cluster)}

Cluster summary:
${clusterSummary(cluster)}
${trimmedAdditionalContext ? `\nAdditional context:\n${trimmedAdditionalContext}\n` : ''}
Use the generation input, output, metadata, and any available trace context to decide how this context should affect the evaluation.

Ignore source run counts, costs, latencies, token counts, and other metrics.`
}

export function buildClusterEvaluationGoal(cluster: Cluster): string {
    return `Detect whether the generation or its trace context shows the "${clusterTitle(cluster)}" pattern. Use the cluster summary as the positive case.`
}

export function buildClusterEvaluationPrompt(cluster: Cluster, evaluationGoal: string): string {
    return `You are judging whether an LLM generation shows a reusable pattern from an LLM Analytics cluster.

Evaluation goal:
${evaluationGoal.trim() || buildClusterEvaluationGoal(cluster)}

Cluster title:
${clusterTitle(cluster)}

Cluster summary:
${clusterSummary(cluster)}

Use the generation input, output, metadata, and any available trace context to decide.

Return true when the generation clearly shows the evaluation goal.
Return false when the generation clearly does not show the evaluation goal.
Return N/A when there is not enough information to decide.

Focus on the evaluation goal, cluster title, and cluster summary only. Ignore source run counts, costs, latencies, token counts, and other metrics.`
}

export function buildClusterTemplateEvaluationPrompt(
    template: LLMJudgeTemplate,
    cluster: Cluster,
    additionalContext?: string
): string {
    return `${template.prompt.trim()}

${buildClusterContextSection(cluster, additionalContext)}`
}
