import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { ThreadItem } from '../../types/streamTypes'
import { QuillSeparatorRow } from './QuillSeparatorRow'

describe('QuillSeparatorRow', () => {
    afterEach(cleanup)

    it.each([
        {
            caseName: 'an extension notice shows its message',
            item: { id: 's1', type: 'status', status: 'extension_notice', isComplete: true, message: 'Picked: Blue' },
            label: 'Picked: Blue',
        },
        {
            caseName: 'an extension notice without a message falls back to the status name',
            item: { id: 's2', type: 'status', status: 'extension_notice', isComplete: true },
            label: 'Extension notice',
        },
    ])('$caseName', ({ item, label }) => {
        render(<QuillSeparatorRow item={item as ThreadItem} live={false} />)
        expect(screen.getByText(label)).toBeInTheDocument()
    })
})
