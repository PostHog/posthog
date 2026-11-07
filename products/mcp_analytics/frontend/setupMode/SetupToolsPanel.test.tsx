import { cleanup, render } from '@testing-library/react'

import type { MCPServerTools } from './setupMode'
import { SetupToolsPanel } from './SetupToolsPanel'

const TEN_TOOLS = Array.from({ length: 10 }, (_, index) => `tool_${index}`)

describe('SetupToolsPanel', () => {
    afterEach(() => {
        cleanup()
    })

    it.each<{ case: string; tools: MCPServerTools | null; failed: boolean; shows: string[]; hides: string[] }>([
        { case: 'loading', tools: null, failed: false, shows: ['Loading your tools'], hides: ["Couldn't load"] },
        { case: 'a failed first load', tools: null, failed: true, shows: ["Couldn't load your tools"], hides: [] },
        {
            case: 'no tools yet',
            tools: { listed: null, called: [] },
            failed: false,
            shows: ['once your agent lists them'],
            hides: ['called'],
        },
        {
            case: 'called tools before any tools/list',
            tools: { listed: null, called: ['search_docs'] },
            failed: false,
            shows: ['search_docs'],
            hides: ['tools called'],
        },
        {
            case: 'a listed set with one call',
            tools: { listed: ['search_docs', 'create_issue'], called: ['search_docs'] },
            failed: false,
            shows: ['1 of 2 tools called', 'create_issue'],
            hides: ['more'],
        },
        {
            case: 'more tools than rows',
            tools: { listed: TEN_TOOLS, called: [] },
            failed: false,
            shows: ['0 of 10 tools called', 'tool_7', '2 more'],
            hides: ['tool_8'],
        },
    ])('renders $case', ({ tools, failed, shows, hides }) => {
        const { container } = render(<SetupToolsPanel tools={tools} failed={failed} />)

        for (const text of shows) {
            expect(container.textContent).toContain(text)
        }
        for (const text of hides) {
            expect(container.textContent).not.toContain(text)
        }
    })
})
