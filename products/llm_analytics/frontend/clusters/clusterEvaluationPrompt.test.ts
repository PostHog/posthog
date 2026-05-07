import { defaultEvaluationTemplates, LLMJudgeTemplate } from '../evaluations/templates'
import { buildClusterTemplateEvaluationPrompt } from './clusterEvaluationPrompt'
import { Cluster } from './types'

const eventTrackingCluster: Cluster = {
    cluster_id: 2,
    size: 126,
    title: 'Event Tracking Troubleshooting',
    description:
        '- Debugging missing, mismatched, or filtered events\n- Includes webhook configuration, initialization, and instrumentation issues\n- Focused on why tracking data is not appearing as expected',
    traces: {},
    centroid: [],
    centroid_x: 0,
    centroid_y: 0,
}

describe('clusterEvaluationPrompt', () => {
    it('keeps the selected LLM judge template prompt and appends cluster context at the bottom', () => {
        const helpfulnessTemplate = defaultEvaluationTemplates.find(
            (template): template is LLMJudgeTemplate =>
                template.key === 'helpfulness' && template.evaluation_type === 'llm_judge'
        )

        if (!helpfulnessTemplate) {
            throw new Error('Expected helpfulness template to exist')
        }

        const prompt = buildClusterTemplateEvaluationPrompt(helpfulnessTemplate, eventTrackingCluster)

        expect(prompt.startsWith(helpfulnessTemplate.prompt)).toBe(true)
        expect(prompt).toContain('## Cluster context added from LLM Analytics')
        expect(prompt).toContain('Source cluster: Event Tracking Troubleshooting')
        expect(prompt).toContain('Debugging missing, mismatched, or filtered events')
        expect(prompt.indexOf('## Cluster context added from LLM Analytics')).toBeGreaterThan(
            helpfulnessTemplate.prompt.length
        )
    })
})
