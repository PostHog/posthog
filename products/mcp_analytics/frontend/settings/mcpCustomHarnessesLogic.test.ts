import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { MCPCustomHarnessApi } from '../generated/api.schemas'
import { mcpCustomHarnessesLogic } from './mcpCustomHarnessesLogic'

const HARNESSES_URL = '/api/projects/:team_id/mcp_analytics/custom_harnesses/'

const harness = (id: string, name: string, match_pattern: string): MCPCustomHarnessApi => ({
    id,
    name,
    match_pattern,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

describe('mcpCustomHarnessesLogic', () => {
    let stored: MCPCustomHarnessApi[]
    let posted: unknown[]
    let deleted: string[]
    let rejectCreate: boolean
    let releaseDelete: () => void
    let deleteReleased: Promise<void>

    beforeEach(() => {
        stored = [harness('a', 'Acme agent', 'acme-agent')]
        posted = []
        deleted = []
        rejectCreate = false
        deleteReleased = new Promise<void>((resolve) => {
            releaseDelete = resolve
        })
        useMocks({
            get: { [HARNESSES_URL]: () => [200, stored] },
            post: {
                [HARNESSES_URL]: async ({ request }) => {
                    const body = (await request.json()) as { name: string; match_pattern: string }
                    posted.push(body)
                    if (rejectCreate) {
                        return [400, { detail: 'A custom harness already uses this pattern.' }]
                    }
                    const created = harness(`id-${posted.length}`, body.name, body.match_pattern)
                    stored = [...stored, created]
                    return [201, created]
                },
            },
            delete: {
                [`${HARNESSES_URL}:id/`]: async ({ params }) => {
                    await deleteReleased
                    deleted.push(params.id as string)
                    stored = stored.filter((h) => h.id !== params.id)
                    return [204]
                },
            },
        })
        initKeaTests()
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')
    })

    const mounted = async (): Promise<ReturnType<typeof mcpCustomHarnessesLogic.build>> => {
        const logic = mcpCustomHarnessesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCustomHarnessesSuccess'])
        return logic
    }

    it('loads the project harnesses on mount', async () => {
        const logic = await mounted()
        expect(logic.values.customHarnesses).toEqual(stored)
    })

    it.each([
        [{ name: '', match_pattern: 'acme' }, { name: 'Enter a name' }],
        [{ name: '   ', match_pattern: 'acme' }, { name: 'Enter a name' }],
        [{ name: 'Acme', match_pattern: '' }, { match_pattern: 'Enter the text to match' }],
    ])('does not send %j and shows %j', async (values, errors) => {
        const logic = await mounted()
        logic.actions.setNewCustomHarnessValues(values)
        logic.actions.submitNewCustomHarness()
        await expectLogic(logic).toDispatchActions(['submitNewCustomHarnessFailure'])
        expect(logic.values.newCustomHarnessValidationErrors).toMatchObject(errors)
        expect(posted).toEqual([])
    })

    it('saves a trimmed name, clears the form and shows the new harness', async () => {
        const logic = await mounted()
        logic.actions.setNewCustomHarnessValues({ name: '  Beta bot ', match_pattern: 'beta-bot' })
        logic.actions.submitNewCustomHarness()
        await expectLogic(logic).toDispatchActions(['submitNewCustomHarnessSuccess', 'loadCustomHarnessesSuccess'])

        expect(posted).toEqual([{ name: 'Beta bot', match_pattern: 'beta-bot' }])
        expect(logic.values.newCustomHarness).toEqual({ name: '', match_pattern: '' })
        expect(logic.values.customHarnesses?.map((h) => h.name)).toEqual(['Acme agent', 'Beta bot'])
    })

    it('keeps what the person typed and shows the server reason when a save fails', async () => {
        rejectCreate = true
        const logic = await mounted()
        logic.actions.setNewCustomHarnessValues({ name: 'Acme copy', match_pattern: 'acme-agent' })
        logic.actions.submitNewCustomHarness()
        await expectLogic(logic).toDispatchActions(['submitNewCustomHarnessFailure'])

        expect(logic.values.newCustomHarness).toEqual({ name: 'Acme copy', match_pattern: 'acme-agent' })
        expect(lemonToast.error).toHaveBeenCalledWith('A custom harness already uses this pattern.')
    })

    it('marks a harness as deleting until the request ends, then reloads the list', async () => {
        const logic = await mounted()
        logic.actions.deleteCustomHarness('a')
        expect(logic.values.deletingHarnessId).toBe('a')

        releaseDelete()
        await expectLogic(logic).toDispatchActions(['deleteCustomHarnessFinished', 'loadCustomHarnessesSuccess'])

        expect(deleted).toEqual(['a'])
        expect(logic.values.deletingHarnessId).toBeNull()
        expect(logic.values.customHarnesses).toEqual([])
    })
})
