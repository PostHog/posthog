import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { PROGRESS_STORAGE_KEY } from '../adventProgressStorage'
import { AdventEntryCard } from './AdventEntryCard'

describe('AdventEntryCard', () => {
    beforeEach(() => {
        window.localStorage.clear()
        initKeaTests()
    })

    it.each([
        ['nothing opened yet', [], {}, 0, 'Open door 3'],
        ['two doors opened before today', [1, 2], { 2: 'james' }, 2, 'Open door 3'],
        ["today's door opened", [1, 2, 3], { 2: 'james' }, 3, 'Open the calendar'],
    ])('shows a hedgehog per opened door with %s', (_, opened, answers, hedgehogs, action) => {
        window.localStorage.setItem(
            PROGRESS_STORAGE_KEY,
            JSON.stringify({ [MOCK_DEFAULT_USER.uuid]: { opened, answers } })
        )

        const { container } = render(<AdventEntryCard phase={{ status: 'open', day: 3 }} />)

        expect(container.querySelectorAll('.AdventEntryCard__door img')).toHaveLength(hedgehogs)
        expect(container.querySelector('[data-attr="advent-entry-card-open"]')?.textContent).toBe(action)
    })
})
