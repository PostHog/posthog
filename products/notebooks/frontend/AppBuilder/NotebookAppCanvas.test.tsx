import { render, screen } from '@testing-library/react'

import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'

import { NotebookAppCanvas } from './NotebookAppCanvas'

describe('NotebookAppCanvas', () => {
    const props = {
        activeTab: 'overview',
        staleNodeIds: {},
        variables: [],
        editing: false,
        selectedId: null,
        canInteract: false,
        onInput: () => {},
        renderOutput: (cell: NotebookBlockNode) => <span>{cell.id}</span>,
    }

    it.each([10, 100])('bounds cell lookup work for %i blocks and reuses it between renders', (count) => {
        let idReads = 0
        const cells: NotebookBlockNode[] = Array.from({ length: count }, (_, index) => ({
            type: 'paragraph',
            get id() {
                idReads++
                return `cell-${index}`
            },
            children: [],
        }))
        const layout = {
            tabs: [{ id: 'overview', title: 'Overview' }],
            blocks: cells.map((_, index) => ({
                id: `block-${index}`,
                kind: 'cell' as const,
                tab_id: 'overview',
                node_id: `cell-${index}`,
            })),
        }
        const { rerender } = render(<NotebookAppCanvas {...props} layout={layout} cells={cells} />)
        expect(screen.getByText(`cell-${count - 1}`)).toBeTruthy()
        expect(idReads).toBeLessThanOrEqual(count * 4)

        idReads = 0
        rerender(<NotebookAppCanvas {...props} layout={layout} cells={cells} selectedId="block-0" />)
        expect(idReads).toBeLessThanOrEqual(count * 2)
    })

    it('refreshes cell output when cells change and keeps the first match for duplicate IDs', () => {
        const first: NotebookBlockNode = { id: 'cell', type: 'code', language: 'text', text: 'First' }
        const second: NotebookBlockNode = { ...first, text: 'Second' }
        const layout = {
            tabs: [{ id: 'overview', title: 'Overview' }],
            blocks: [
                { id: 'block', kind: 'cell' as const, tab_id: 'overview', node_id: 'cell', display: 'source' as const },
            ],
        }
        const { rerender } = render(<NotebookAppCanvas {...props} layout={layout} cells={[first, second]} />)
        expect(screen.getByText(/First/)).toBeTruthy()
        expect(screen.queryByText(/Second/)).toBeNull()

        rerender(<NotebookAppCanvas {...props} layout={layout} cells={[second]} />)
        expect(screen.getByText(/Second/)).toBeTruthy()
        expect(screen.queryByText(/First/)).toBeNull()

        rerender(<NotebookAppCanvas {...props} layout={layout} cells={[]} />)
        expect(screen.getByText(/This source cell is no longer in the notebook/)).toBeTruthy()
    })
})
