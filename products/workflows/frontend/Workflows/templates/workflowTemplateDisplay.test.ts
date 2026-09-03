import type { HogFlowTemplate } from '../hogflows/types'
import { getTemplateTrigger, isAiTemplate } from './workflowTemplateDisplay'

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
})
