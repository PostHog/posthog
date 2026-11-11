import type { HogFlow, HogFlowAction } from '../types'
import {
    HIDE_SURVEY_TEMPLATE_ID,
    getAwaitedSurveyId,
    getNextAction,
    insertSurveyResponseWait,
    retargetSurveyResponseWait,
} from './surveyResponseWait'

const action = (id: string, type: string, config: Record<string, unknown> = {}): HogFlowAction =>
    ({ id, type, name: id, description: '', config }) as HogFlowAction

const workflow: Pick<HogFlow, 'actions' | 'edges'> = {
    actions: [
        action('trigger', 'trigger'),
        action('show', 'function', { template_id: 'template-posthog-show-survey', inputs: {} }),
        action('exit', 'exit'),
    ],
    edges: [
        { from: 'trigger', to: 'show', type: 'continue' },
        { from: 'show', to: 'exit', type: 'continue' },
    ],
}

const hideConfig = {
    template_id: HIDE_SURVEY_TEMPLATE_ID,
    inputs: { distinct_id: { value: '{event.distinct_id}' } },
} as Extract<HogFlowAction, { type: 'function' }>['config']

describe('insertSurveyResponseWait', () => {
    it('waits for the survey answer and hides the survey on both paths before the old next step', () => {
        const result = insertSurveyResponseWait(workflow, 'show', 'survey-1', hideConfig)!

        const wait = getNextAction(result, 'show')!
        expect(getAwaitedSurveyId(wait)).toEqual('survey-1')

        const hide = result.actions.find((a) => a.type === 'function' && a.id !== 'show')!
        expect(hide.config).toMatchObject({
            template_id: HIDE_SURVEY_TEMPLATE_ID,
            inputs: { survey_id: { value: 'survey-1' }, distinct_id: { value: '{event.distinct_id}' } },
        })
        expect(result.edges.filter((edge) => edge.from === wait.id)).toEqual([
            { from: wait.id, to: hide.id, type: 'branch', index: 0 },
            { from: wait.id, to: hide.id, type: 'continue' },
        ])
        expect(result.edges.filter((edge) => edge.from === hide.id)).toEqual([
            { from: hide.id, to: 'exit', type: 'continue' },
        ])
        expect(result.actions[result.actions.length - 1].id).toEqual('exit')
    })

    it('refuses a step that has no single next step', () => {
        const branched = {
            ...workflow,
            edges: [...workflow.edges, { from: 'show', to: 'exit', type: 'branch' as const }],
        }
        expect(insertSurveyResponseWait(branched, 'show', 'survey-1', hideConfig)).toBeNull()
    })
})

describe('retargetSurveyResponseWait', () => {
    it('points the wait and its hide step at the new survey', () => {
        const inserted = insertSurveyResponseWait(workflow, 'show', 'survey-1', hideConfig)!
        const result = retargetSurveyResponseWait(inserted, 'show', 'survey-2')!

        expect(getAwaitedSurveyId(getNextAction(result, 'show'))).toEqual('survey-2')
        const hide = result.actions.find((a) => a.type === 'function' && a.id !== 'show')!
        expect(hide.config).toMatchObject({ inputs: { survey_id: { value: 'survey-2' } } })
        expect(result.edges).toEqual(inserted.edges)
    })
})
