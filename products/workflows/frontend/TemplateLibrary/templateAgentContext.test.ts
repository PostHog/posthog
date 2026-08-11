import {
    TEMPLATE_EDITOR_STATE_MAX_CHARS,
    buildTemplateAgentContext,
    serializeTemplateEditorState,
} from './templateAgentContext'
import { MessageTemplate } from './types'

function templateWith(email: Record<string, unknown>): MessageTemplate {
    return {
        id: 'template-1',
        name: 'Welcome email',
        description: '',
        content: { templating: 'liquid', email },
        created_at: null,
        updated_at: null,
        created_by: null,
    } as unknown as MessageTemplate
}

describe('templateAgentContext', () => {
    describe('serializeTemplateEditorState', () => {
        // The rendered html is re-derived server-side from the design on every save, so shipping it
        // alongside the design would double (or worse) the payload attached to every message.
        it('drops the rendered html when a design is present, keeping it on html-only templates', () => {
            const withDesign = serializeTemplateEditorState(
                templateWith({ design: { rows: ['r1'] }, html: '<html>rendered</html>' })
            )
            expect(withDesign).not.toContain('rendered')
            expect(withDesign).toContain('r1')
            expect(withDesign).not.toContain('elided for size')

            const htmlOnly = serializeTemplateEditorState(templateWith({ html: '<html>only body</html>' }))
            expect(htmlOnly).toContain('only body')
        })

        it('elides the design once the serialized state exceeds the cap, keeping the JSON parseable', () => {
            const serialized = serializeTemplateEditorState(
                templateWith({ design: { blocks: 'x'.repeat(TEMPLATE_EDITOR_STATE_MAX_CHARS) }, subject: 'Hi' })
            )

            expect(serialized.length).toBeLessThan(TEMPLATE_EDITOR_STATE_MAX_CHARS)
            const email = JSON.parse(serialized).content.email
            expect(email.design).toContain('elided for size')
            expect(email.subject).toBe('Hi')
        })
    })

    describe('buildTemplateAgentContext', () => {
        // A ref chip for an unsaved template would hand the agent a `new` id that no fetch tool
        // resolves; the live editor state must be attached either way.
        it('attaches a template ref only for saved templates, with the live editor state alongside', () => {
            const template = templateWith({ design: null, html: '' })

            const saved = buildTemplateAgentContext(template, 'template-1')
            expect(saved.find((item) => item.type === 'message_template')).toMatchObject({
                key: 'template-1',
                label: 'Welcome email',
            })
            expect(saved.some((item) => item.type === 'message_template_editor_state')).toBe(true)

            const unsaved = buildTemplateAgentContext(template, 'new')
            expect(unsaved.some((item) => item.type === 'message_template')).toBe(false)
            expect(unsaved.some((item) => item.type === 'message_template_editor_state')).toBe(true)
        })
    })
})
