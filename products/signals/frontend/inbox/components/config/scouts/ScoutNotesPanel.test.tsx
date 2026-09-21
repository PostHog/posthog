import { cleanup, fireEvent, render } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ScoutNotesPanel } from './ScoutNotesPanel'

const SKILL_NAME = 'signals-scout-daily-digest'
const OPENING = 'The dashboard was re-anchored last Thursday, so treat anything before it as a different metric.'
const TAIL = 'Retire this note once the first clean week of baselines is in.'
const LONG_NOTE = `${OPENING} ${'Baselines rebuild slowly. '.repeat(20)}${TAIL}`

describe('ScoutNotesPanel', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/signals/scout/notes/': [
                    {
                        id: 'note-1',
                        content: LONG_NOTE,
                        origin: 'human',
                        skill_name: SKILL_NAME,
                        created_by_name: 'Someone',
                        created_at: '2026-08-21T10:00:00Z',
                        expires_at: null,
                    },
                ],
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    it('shows the opening of a long note until it is expanded', async () => {
        const { findByText, getByText, queryByText } = render(<ScoutNotesPanel skillName={SKILL_NAME} />)

        // Matching on the tail rather than the whole note: the preview cuts at a word boundary, so
        // the exact cut point is not the thing worth pinning.
        expect(await findByText(new RegExp(OPENING))).toBeTruthy()
        expect(queryByText(new RegExp(TAIL))).toBeNull()

        fireEvent.click(getByText('Show more'))

        expect(getByText(new RegExp(TAIL))).toBeTruthy()
    })
})
