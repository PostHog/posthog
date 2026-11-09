import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { codeEmailLogic } from './codeEmailLogic'

const receipt: CodeEmailApi = {
    id: 'receipt-id',
    key: 'receipt',
    hog_flow_id: 'flow-receipt',
    description: 'Sent after a payment',
    tags: ['billing'],
    sensitive: true,
    source_url: null,
    created_at: '2026-01-01T00:00:00Z',
}

describe('codeEmailLogic', () => {
    let patches: Record<string, unknown>[]

    beforeEach(() => {
        patches = []
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_code_emails/receipt-id/': receipt,
                '/api/projects/:team_id/transactional_code_emails/gone-id/': () => [404, { detail: 'Not found.' }],
            },
            patch: {
                '/api/projects/:team_id/transactional_code_emails/receipt-id/': async ({ request }) => {
                    const fields = (await request.json()) as Record<string, unknown>
                    patches.push(fields)
                    return [200, { ...receipt, ...fields }]
                },
            },
        })
        initKeaTests()
    })

    it('resolves an email that no longer exists to null, so the page shows not found', async () => {
        const logic = codeEmailLogic({ id: 'gone-id' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.codeEmail).toBeNull()
        logic.unmount()
    })

    it('links a source file by sending only its link, and closes the form', async () => {
        const logic = codeEmailLogic({ id: 'receipt-id' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSourceFormOpen(true)

        const link = 'https://github.com/acme/web/blob/main/src/emails/receipt.tsx'
        logic.actions.linkSourceFile(link)
        await expectLogic(logic).toFinishAllListeners()

        expect(patches).toEqual([{ source_url: link }])
        expect(logic.values.codeEmail?.source_url).toEqual(link)
        expect(logic.values.sourceFormOpen).toBe(false)
        logic.unmount()
    })
})
