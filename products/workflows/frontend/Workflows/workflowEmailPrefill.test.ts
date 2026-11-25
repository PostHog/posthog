import { draftMessage } from '../MessageAudience/messageDrafts'
import { prefilledWorkflow, templatePrefilledWorkflow, withEmailSender } from './workflowEmailPrefill'
import { NEW_WORKFLOW } from './workflowLogic'
import type { WorkflowTriggerConfig } from './workflowTriggerPrefill'

const EVENT_TRIGGER: WorkflowTriggerConfig = {
    type: 'event',
    filters: { events: [{ id: '$exception', name: '$exception', type: 'events' }] },
}
const BATCH_TRIGGER: WorkflowTriggerConfig = { type: 'batch', filters: { properties: [] } }

describe('workflowEmailPrefill', () => {
    it.each([
        {
            trigger: 'an event trigger',
            config: EVENT_TRIGGER,
            masking: { hash: '{person.id}', ttl: null, threshold: null },
        },
        { trigger: 'a batch trigger', config: BATCH_TRIGGER, masking: undefined },
    ])('opens $trigger with a draft email as trigger, email, exit', ({ config, masking }) => {
        const workflow = prefilledWorkflow(NEW_WORKFLOW, config, draftMessage({ kind: 'issue_hit' }))

        expect(workflow.actions.map((action) => action.type)).toEqual(['trigger', 'function_email', 'exit'])
        expect(workflow.edges.map(({ from, to }) => [from, to])).toEqual([
            ['trigger_node', 'action_function_email_prefilled'],
            ['action_function_email_prefilled', 'exit_node'],
        ])
        expect((workflow.actions[1].config as any).inputs.email.value).toMatchObject({
            to: { email: '{{ person.properties.email }}' },
            subject: 'Sorry about the error you ran into',
        })
        expect(workflow.trigger_masking).toEqual(masking)
    })

    it('keeps a sender the email step already has and fills the ones without', () => {
        const workflow = prefilledWorkflow(NEW_WORKFLOW, EVENT_TRIGGER, draftMessage({ kind: 'issue_hit' }))
        const filled = withEmailSender(workflow, 5)
        const refilled = withEmailSender(filled.workflow, 9)

        expect(filled.filled).toBe(true)
        expect((filled.workflow.actions[1].config as any).inputs.email.value.from).toEqual({ integrationId: 5 })
        expect(refilled).toEqual({ workflow: filled.workflow, filled: false })
    })

    it.each([
        [
            'a link the email editor saved with encoded spaces',
            '<a href="{{%20variables.link%20}}">',
            '<a href="{{%20event.properties.link%20}}">',
        ],
        ['a bracket lookup', "{{ variables['order-id'] }}", "{{ event.properties['order-id'] }}"],
        ['whitespace control', '{{-variables.name-}}', '{{-event.properties.name-}}'],
        [
            'a loop',
            '{% for item in variables.items %}{{ item }}{% endfor %}',
            '{% for item in event.properties.items %}{{ item }}{% endfor %}',
        ],
        [
            'a range bound',
            '{% for i in (1..variables.count) %}{{ i }}{% endfor %}',
            '{% for i in (1..event.properties.count) %}{{ i }}{% endfor %}',
        ],
        [
            'a property that ends in variables',
            '{{ person.properties.variables.x }}',
            '{{ person.properties.variables.x }}',
        ],
        ['a hyphenated name that ends in variables', '{{ my-variables.x }}', '{{ my-variables.x }}'],
        ['an assignment of all variables', '{% assign data = variables %}', '{% assign data = event.properties %}'],
        [
            'a quoted key that names variables',
            "{{ variables['variables.name'] }}",
            "{{ event.properties['variables.name'] }}",
        ],
        [
            'a quoted fallback link',
            '{{ variables.link | default: "https://example.com/variables.html" }}',
            '{{ event.properties.link | default: "https://example.com/variables.html" }}',
        ],
        [
            'a fallback the email editor saved with encoded quotes',
            '{{ variables.link | default: &quot;/variables.html&quot; }}',
            '{{ event.properties.link | default: &quot;/variables.html&quot; }}',
        ],
        [
            'a raw block, which prints its text as written',
            '{% raw %}{{ variables.name }}{% endraw %} {{ variables.name }}',
            '{% raw %}{{ variables.name }}{% endraw %} {{ event.properties.name }}',
        ],
        [
            'a comment block',
            '{%- comment -%}{{ variables.name }}{%- endcomment -%}{{ variables.name }}',
            '{%- comment -%}{{ variables.name }}{%- endcomment -%}{{ event.properties.name }}',
        ],
        [
            'its own assignment of variables, as the name then reads that value',
            '{% assign variables = person.properties %}{{ variables.name }}',
            '{% assign variables = person.properties %}{{ variables.name }}',
        ],
        [
            'its own capture of variables',
            '{% capture variables %}Hi{% endcapture %}{{ variables }}',
            '{% capture variables %}Hi{% endcapture %}{{ variables }}',
        ],
        [
            'an assignment of variables inside a raw block, which Liquid only prints',
            '{% raw %}{% assign variables = 1 %}{% endraw %}{{ variables.name }}',
            '{% raw %}{% assign variables = 1 %}{% endraw %}{{ event.properties.name }}',
        ],
        [
            'a closing delimiter that trims whitespace',
            '{%- assign data = variables-%}',
            '{%- assign data = event.properties-%}',
        ],
        [
            'a quoted value with an escaped quote',
            "{% assign hint = 'don\\'t type variables.name' %}{{ variables.name }}",
            "{% assign hint = 'don\\'t type variables.name' %}{{ event.properties.name }}",
        ],
        [
            'its own assignment of variables inside a liquid tag',
            '{% liquid\n  assign variables = person.properties\n%}{{ variables.name }}',
            '{% liquid\n  assign variables = person.properties\n%}{{ variables.name }}',
        ],
        [
            'text that names the words for variables',
            '<p>Look for variables</p>{{ variables.name }}',
            '<p>Look for variables</p>{{ event.properties.name }}',
        ],
    ])('copies a template email with %s', (_, html, expected) => {
        const workflow = templatePrefilledWorkflow(NEW_WORKFLOW, EVENT_TRIGGER, {
            name: 'Receipt',
            content: { templating: 'liquid', email: { html } },
        } as any)

        expect((workflow.actions[1].config as any).inputs.email.value.html).toBe(expected)
    })

    it('sends a template email from a workflow as marketing email, so the save is accepted', () => {
        const workflow = templatePrefilledWorkflow(NEW_WORKFLOW, EVENT_TRIGGER, {
            name: 'Receipt',
            content: { templating: 'liquid', email: { html: '<p>Hi</p>' } },
        } as any)

        expect(workflow.actions[1].config).not.toHaveProperty('message_category_type')
    })

    it('copies a template subject that reads variables when only its body assigns its own', () => {
        const workflow = templatePrefilledWorkflow(NEW_WORKFLOW, EVENT_TRIGGER, {
            name: 'Receipt',
            content: {
                templating: 'liquid',
                email: { subject: 'Order {{ variables.id }}', html: '{% assign variables = 1 %}{{ variables }}' },
            },
        } as any)

        expect((workflow.actions[1].config as any).inputs.email.value).toMatchObject({
            subject: 'Order {{ event.properties.id }}',
            html: '{% assign variables = 1 %}{{ variables }}',
        })
    })

    it('copies a sender address that reads variables when only the sender name assigns its own', () => {
        const workflow = templatePrefilledWorkflow(NEW_WORKFLOW, EVENT_TRIGGER, {
            name: 'Receipt',
            content: {
                templating: 'liquid',
                email: {
                    from: { integrationId: 5, email: '{{ variables.sender }}', name: '{% assign variables = 1 %}Shop' },
                    html: '<p>Hi</p>',
                },
            },
        } as any)

        expect((workflow.actions[1].config as any).inputs.email.value.from).toEqual({
            integrationId: 5,
            email: '{{ event.properties.sender }}',
            name: '{% assign variables = 1 %}Shop',
        })
    })
})
