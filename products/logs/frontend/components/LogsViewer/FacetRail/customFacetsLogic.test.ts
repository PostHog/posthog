import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { logsCustomFacetsCreate, logsCustomFacetsList } from '../../../generated/api'
import { customFacetsLogic } from './customFacetsLogic'

jest.mock('../../../generated/api', () => ({
    logsCustomFacetsList: jest.fn(),
    logsCustomFacetsCreate: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { error: jest.fn() },
}))

const listMock = logsCustomFacetsList as jest.Mock
const createMock = logsCustomFacetsCreate as jest.Mock
const errorToast = lemonToast.error as jest.Mock

describe('customFacetsLogic', () => {
    let logic: ReturnType<typeof customFacetsLogic.build>

    beforeEach(async () => {
        listMock.mockResolvedValue([{ key: 'cloud.provider', attribute_type: 'resource' }])
        createMock.mockResolvedValue([])
        initKeaTests()
        logic = customFacetsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    it("loads the user's custom facets on mount", () => {
        expect(logic.values.customFacetEntries).toEqual([{ key: 'cloud.provider', attribute_type: 'resource' }])
    })

    it('adds a facet optimistically and persists the new full set', async () => {
        await expectLogic(logic, () => logic.actions.addCustomFacet('faas.id', 'resource')).toFinishAllListeners()

        const expected = [
            { key: 'cloud.provider', attribute_type: 'resource' },
            { key: 'faas.id', attribute_type: 'resource' },
        ]
        expect(logic.values.customFacetEntries).toEqual(expected)
        expect(createMock).toHaveBeenCalledWith(expect.any(String), expected)
    })

    it('ignores a duplicate key', async () => {
        await expectLogic(logic, () =>
            logic.actions.addCustomFacet('cloud.provider', 'resource')
        ).toFinishAllListeners()
        expect(logic.values.customFacetEntries).toEqual([{ key: 'cloud.provider', attribute_type: 'resource' }])
    })

    it('removes a facet and persists the remaining set', async () => {
        await expectLogic(logic, () => logic.actions.removeCustomFacet('cloud.provider')).toFinishAllListeners()
        expect(logic.values.customFacetEntries).toEqual([])
        expect(createMock).toHaveBeenCalledWith(expect.any(String), [])
    })

    it('renders resource entries as Custom facets but skips log entries', async () => {
        await expectLogic(logic, () => logic.actions.addCustomFacet('http.method', 'log')).toFinishAllListeners()

        // The log entry is stored…
        expect(logic.values.customFacetEntries).toHaveLength(2)
        // …but only the resource one becomes a rail facet (log attrs need the facet_attribute path).
        expect(logic.values.customFacets).toHaveLength(1)
        expect(logic.values.customFacets[0]).toMatchObject({
            group: 'Custom',
            removable: true,
            source: { type: 'resourceAttribute', key: 'cloud.provider' },
        })
    })

    it('toasts and rolls back to the server set when a save fails', async () => {
        createMock.mockRejectedValueOnce(new Error('save failed'))

        // The optimistic add lands, the persist rejects, and the catch reloads from the server —
        // which still only has the original facet, so the unsaved one is dropped from the rail.
        await expectLogic(logic, () => logic.actions.addCustomFacet('faas.id', 'resource')).toDispatchActions([
            'addCustomFacet',
            'loadCustomFacets',
            'setCustomFacets',
        ])

        expect(errorToast).toHaveBeenCalledTimes(1)
        expect(logic.values.customFacetEntries).toEqual([{ key: 'cloud.provider', attribute_type: 'resource' }])
    })

    it('toasts and keeps the current set when a load fails', async () => {
        listMock.mockRejectedValueOnce(new Error('load failed'))

        await expectLogic(logic, () => logic.actions.loadCustomFacets()).toFinishAllListeners()

        expect(errorToast).toHaveBeenCalledTimes(1)
        // A failed reload must not wipe what was already loaded.
        expect(logic.values.customFacetEntries).toEqual([{ key: 'cloud.provider', attribute_type: 'resource' }])
    })
})
