import type { HogFlowTemplate } from '../hogflows/types'
import { getOrderedActions, getTemplateTrigger, isAiTemplate } from './workflowTemplateDisplay'

describe('workflowTemplateDisplay', () => {
    function templateWith(partial: Partial<HogFlowTemplate>): HogFlowTemplate {
        return { actions: [], tags: [], ...partial } as unknown as HogFlowTemplate
    }

    describe('isAiTemplate', () => {
        it.each([
            ['template-posthog-create-task', true],
            ['template-posthog-run-scout', true],
            ['template-slack', false],
        ])('reads a %s step as AI: %s', (templateId, expected) => {
            const template = templateWith({
                actions: [{ id: 'a', type: 'function', name: 'a', config: { template_id: templateId } }] as any,
            })
            expect(isAiTemplate(template)).toBe(expected)
        })

        it('reads the ai tag as AI, for a template that reaches an agent another way', () => {
            expect(isAiTemplate(templateWith({ tags: ['AI', 'support'] }))).toBe(true)
        })

        it('does not read a step without a template_id as AI', () => {
            const template = templateWith({
                actions: [{ id: 'a', type: 'delay', name: 'a', config: { delay_duration: '1d' } }] as any,
            })
            expect(isAiTemplate(template)).toBe(false)
        })
    })

    describe('getTemplateTrigger', () => {
        it('reads the trigger from the action graph, which is where the editor keeps it', () => {
            const template = templateWith({
                actions: [{ id: 't', type: 'trigger', name: 't', config: { type: 'schedule' } }] as any,
            })
            expect(getTemplateTrigger(template)).toEqual({ type: 'schedule', label: 'Starts on a schedule' })
        })

        it('labels a trigger type it does not know, rather than dropping the line', () => {
            const template = templateWith({
                actions: [{ id: 't', type: 'trigger', name: 't', config: { type: 'brand-new' } }] as any,
            })
            expect(getTemplateTrigger(template)?.label).toEqual('Starts on a trigger')
        })
    })

    describe('getOrderedActions', () => {
        const actions = [
            { id: 'trigger', type: 'trigger', name: 'trigger', config: {} },
            { id: 'email', type: 'function_email', name: 'email', config: {} },
            { id: 'delay', type: 'delay', name: 'delay', config: {} },
            { id: 'exit', type: 'exit', name: 'exit', config: {} },
        ] as any

        it('walks the edges rather than the array, which is creation order', () => {
            const edges = [
                { from: 'trigger', to: 'delay', type: 'continue' },
                { from: 'delay', to: 'email', type: 'continue' },
                { from: 'email', to: 'exit', type: 'continue' },
            ] as any
            expect(getOrderedActions(actions, edges).map((action) => action.id)).toEqual([
                'trigger',
                'delay',
                'email',
                'exit',
            ])
        })

        it('takes a met condition before the default path, which usually just exits', () => {
            const branching = [
                { id: 'trigger', type: 'trigger', name: 'trigger', config: {} },
                { id: 'branch', type: 'conditional_branch', name: 'branch', config: {} },
                { id: 'email', type: 'function_email', name: 'email', config: {} },
                { id: 'exit', type: 'exit', name: 'exit', config: {} },
            ] as any
            const edges = [
                { from: 'trigger', to: 'branch', type: 'continue' },
                { from: 'branch', to: 'exit', type: 'continue' },
                { from: 'branch', to: 'email', type: 'branch', index: 0 },
            ] as any
            expect(getOrderedActions(branching, edges).map((action) => action.id)).toEqual([
                'trigger',
                'branch',
                'email',
                'exit',
            ])
        })

        it('keeps an action the edges never reach', () => {
            const edges = [{ from: 'trigger', to: 'exit', type: 'continue' }] as any
            expect(getOrderedActions(actions, edges).map((action) => action.id)).toEqual([
                'trigger',
                'exit',
                'email',
                'delay',
            ])
        })

        it('falls back to the array when there is no trigger to walk from', () => {
            expect(getOrderedActions(actions.slice(1), [])).toEqual(actions.slice(1))
        })
    })
})
