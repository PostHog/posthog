import { HogFlow, HogFlowAction } from './hogflows/types'
import { AiTaskPromptChange, getAiTaskPromptChanges } from './workflowLogic'

const functionStep = (id: string, prompt: string, templateId = 'template-posthog-create-task'): HogFlowAction => ({
    id,
    type: 'function',
    name: `Step ${id}`,
    description: '',
    created_at: 0,
    updated_at: 0,
    config: { template_id: templateId, inputs: { prompt: { value: prompt } } },
})

const makeWorkflow = (live: HogFlowAction[], staged: HogFlowAction[]): HogFlow =>
    ({
        id: 'wf-publish-1',
        name: 'Publish test',
        actions: live,
        edges: [],
        status: 'active',
        draft: { actions: staged },
    }) as unknown as HogFlow

describe('getAiTaskPromptChanges', () => {
    test.each<[string, HogFlowAction[], HogFlowAction[], AiTaskPromptChange[]]>([
        [
            'returns live and staged instructions for a changed AI task step',
            [functionStep('a', 'Triage the ticket')],
            [functionStep('a', 'Triage the ticket and tag it')],
            [
                {
                    actionId: 'a',
                    stepName: 'Step a',
                    livePrompt: 'Triage the ticket',
                    stagedPrompt: 'Triage the ticket and tag it',
                },
            ],
        ],
        [
            'skips an AI task step with unchanged instructions',
            [functionStep('a', 'Same')],
            [functionStep('a', 'Same')],
            [],
        ],
        ['skips an AI task step the draft adds', [], [functionStep('a', 'New step')], []],
        [
            'treats a step stored without inputs as having empty instructions',
            [{ ...functionStep('a', ''), config: { template_id: 'template-posthog-create-task' } } as HogFlowAction],
            [functionStep('a', 'Triage the ticket')],
            [{ actionId: 'a', stepName: 'Step a', livePrompt: '', stagedPrompt: 'Triage the ticket' }],
        ],
        [
            'skips a function step from another template',
            [functionStep('a', 'Old', 'template-webhook')],
            [functionStep('a', 'New', 'template-webhook')],
            [],
        ],
    ])('%s', (_, live, staged, expected) => {
        expect(getAiTaskPromptChanges(makeWorkflow(live, staged))).toEqual(expected)
    })
})
