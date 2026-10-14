import { wrapWithPosthogContext } from 'products/posthog_ai/frontend/api/logics'

import { getNotebookBtwContext } from './notebookBtwContext'

describe('notebook btw context', () => {
    it.each([undefined, 'Selected paragraph'])(
        'sends notebook content and selection as untrusted text (%s)',
        (selectedMarkdown) => {
            const message = wrapWithPosthogContext(
                'Explain this',
                getNotebookBtwContext({ markdown: '# Unsaved notebook\n\nDraft paragraph', selectedMarkdown })
            )
            const [trusted, untrusted] = message.split('<posthog_untrusted_context>')
            expect(trusted).toContain('Do not edit the notebook')
            expect(trusted).not.toContain('Draft paragraph')
            expect(untrusted).toContain('Draft paragraph')
            if (selectedMarkdown) {
                expect(untrusted).toContain(selectedMarkdown)
            }
        }
    )

    it('bounds the snapshot and selection and marks omitted content', () => {
        const items = getNotebookBtwContext({ markdown: 'a'.repeat(80_000), selectedMarkdown: 'b'.repeat(40_000) })
        expect(items[1].value).toBe('a'.repeat(64_000) + '\n[Remaining content omitted]')
        expect(items[2].value).toBe('b'.repeat(32_000) + '\n[Remaining content omitted]')
    })
})
