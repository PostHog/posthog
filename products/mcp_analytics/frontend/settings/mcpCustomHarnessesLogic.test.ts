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
    let patched: { id: string; body: unknown }[]
    let deleted: string[]
    let rejectCreate: boolean
    let releaseDelete: () => void
    let deleteReleased: Promise<void>

    beforeEach(() => {
        stored = [harness('a', 'Acme agent', 'acme-agent')]
        posted = []
        patched = []
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
            patch: {
                [`${HARNESSES_URL}:id/`]: async ({ params, request }) => {
                    const body = (await request.json()) as Partial<MCPCustomHarnessApi>
                    patched.push({ id: params.id as string, body })
                    stored = stored.map((h) => (h.id === params.id ? { ...h, ...body } : h))
                    return [200, stored.find((h) => h.id === params.id)]
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
        logic.actions.startAddingHarness()
        logic.actions.setCustomHarnessFormValues(values)
        logic.actions.submitCustomHarnessForm()
        await expectLogic(logic).toDispatchActions(['submitCustomHarnessFormFailure'])
        expect(logic.values.customHarnessFormValidationErrors).toMatchObject(errors)
        expect(posted).toEqual([])
    })

    it('saves a trimmed name, closes the form and shows the new harness', async () => {
        const logic = await mounted()
        logic.actions.startAddingHarness()
        logic.actions.setCustomHarnessFormValues({ name: '  Beta bot ', match_pattern: 'beta-bot' })
        logic.actions.submitCustomHarnessForm()
        await expectLogic(logic).toDispatchActions(['submitCustomHarnessFormSuccess', 'loadCustomHarnessesSuccess'])

        expect(posted).toEqual([{ name: 'Beta bot', match_pattern: 'beta-bot' }])
        expect(logic.values.editingHarnessId).toBeNull()
        expect(logic.values.customHarnesses?.map((h) => h.name)).toEqual(['Acme agent', 'Beta bot'])
    })

    it('edits a harness in place with the values it already has', async () => {
        const logic = await mounted()
        logic.actions.startEditingHarness(stored[0])
        expect(logic.values.editingHarnessId).toBe('a')
        expect(logic.values.customHarnessForm).toEqual({ name: 'Acme agent', match_pattern: 'acme-agent' })

        logic.actions.setCustomHarnessFormValues({ name: 'Acme assistant' })
        logic.actions.submitCustomHarnessForm()
        await expectLogic(logic).toDispatchActions(['submitCustomHarnessFormSuccess', 'loadCustomHarnessesSuccess'])

        expect(posted).toEqual([])
        expect(patched).toEqual([{ id: 'a', body: { name: 'Acme assistant', match_pattern: 'acme-agent' } }])
        expect(logic.values.editingHarnessId).toBeNull()
        expect(logic.values.customHarnesses?.map((h) => h.name)).toEqual(['Acme assistant'])
    })

    it('cancelling an edit clears the form so the next add starts empty', async () => {
        const logic = await mounted()
        logic.actions.startEditingHarness(stored[0])
        logic.actions.cancelEditingHarness()
        logic.actions.startAddingHarness()

        expect(logic.values.editingHarnessId).toBe('new')
        expect(logic.values.customHarnessForm).toEqual({ name: '', match_pattern: '' })
    })

    it('keeps what the person typed and shows the server reason when a save fails', async () => {
        rejectCreate = true
        const logic = await mounted()
        logic.actions.startAddingHarness()
        logic.actions.setCustomHarnessFormValues({ name: 'Acme copy', match_pattern: 'acme-agent' })
        logic.actions.submitCustomHarnessForm()
        await expectLogic(logic).toDispatchActions(['submitCustomHarnessFormFailure'])

        expect(logic.values.editingHarnessId).toBe('new')
        expect(logic.values.customHarnessForm).toEqual({ name: 'Acme copy', match_pattern: 'acme-agent' })
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
