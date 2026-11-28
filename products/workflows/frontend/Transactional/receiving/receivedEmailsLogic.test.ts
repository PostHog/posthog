import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { receivedEmailsLogic } from './receivedEmailsLogic'

const EMAIL = { id: 'e1', subject: 'Hello', status: 'received', envelope_recipients: ['a@b.example'] }

describe('receivedEmailsLogic', () => {
    let logic: ReturnType<typeof receivedEmailsLogic.build>
    let page: Record<string, unknown>

    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/received_emails/': () => [200, page] } })
        initKeaTests()
    })

    const mount = async (nextPage: Record<string, unknown>): Promise<void> => {
        page = nextPage
        logic = receivedEmailsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadEmailsSuccess']).toFinishAllListeners()
    }

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['nothing has arrived', { results: [], has_more: false, filtered_count: 0 }, true],
        // A forwarding confirmation code can land under Filtered, so the setup page must not hide it.
        ['only filtered mail has arrived', { results: [], has_more: false, filtered_count: 2 }, false],
        ['mail has arrived', { results: [EMAIL], has_more: false, filtered_count: 0 }, false],
    ])('when %s, waiting for mail is %s', async (_, page, expected) => {
        await mount(page)
        expect(logic.values.isWaitingForMail).toBe(expected)
    })

    it('does not show setup when a search finds nothing', async () => {
        await mount({ results: [], has_more: false, filtered_count: 0 })
        logic.actions.setFilters({ search: 'nobody' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.isWaitingForMail).toBe(false)
    })
})
