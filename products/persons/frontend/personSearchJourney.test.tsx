import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { createCustomerJourney } from 'lib/customerJourneys/createCustomerJourney'
import * as journeyStarter from 'lib/customerJourneys/startCustomerJourney'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { isActorsQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'

import { personsSceneLogic } from './logics/personsSceneLogic'
import { getPersonSearchJourney } from './personSearchJourney'

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))
jest.mock('lib/utils/kea-logic-builders', () => ({ permanentlyMount: () => () => {} }))

function PersonTable(): JSX.Element {
    const { query } = useValues(personsSceneLogic)
    const { setQuery } = useActions(personsSceneLogic)
    return (
        <Query
            uniqueKey="persons-query"
            attachTo={personsSceneLogic()}
            query={{ ...query, showSearch: true, showCount: true }}
            setQuery={setQuery}
            context={{
                dataNodeLogicKey: 'person-journey-test',
                refresh: 'blocking',
                queryJourney: getPersonSearchJourney(query),
            }}
        />
    )
}

describe('person search query-to-table journey', () => {
    let capture: jest.Mock
    let resolve: (response: any) => void

    beforeEach(() => {
        initKeaTests()
        personsSceneLogic.mount()
        capture = jest.fn()
        jest.spyOn(journeyStarter, 'startCustomerJourney').mockImplementation((options) =>
            createCustomerJourney(
                {
                    ...options,
                    attempt_id: options.attempt_id!,
                    region: 'US',
                    project_id: 1,
                    organization_id: 'synthetic-org',
                    registry_version: 'test',
                },
                { now: () => 1, capture, visibility: { getState: () => 'visible', subscribe: () => () => {} } }
            )
        )
        ;(performQuery as jest.Mock).mockImplementation((query) =>
            query.kind === NodeKind.HogQLQuery || query.select?.[0]?.startsWith('count(')
                ? Promise.resolve({ results: [[0]] })
                : new Promise((yes) => {
                      resolve = yes
                  })
        )
    })

    afterEach(() => {
        cleanup()
        personsSceneLogic.unmount()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it.each([{ results: [] }, { results: [['synthetic-result-secret']] }])(
        'finishes only when the actual table commits %j',
        async ({ results }) => {
            const view = render(<PersonTable />)
            expect(capture.mock.calls).toEqual([
                ['customer_journey_started', expect.objectContaining({ journey_name: 'person_search' })],
            ])
            const logic = dataNodeLogic.findMounted({ key: 'person-journey-test' })!
            await act(async () => {
                resolve({ results, columns: ['synthetic_column'], types: ['String'], hasMore: false })
                await expectLogic(logic).toFinishAllListeners()
            })
            expect(capture.mock.calls.at(-1)?.[1]).toMatchObject({ outcome: 'usable', first_useful_ms: 0 })
            expect(JSON.stringify(capture.mock.calls)).not.toMatch(/synthetic-result-secret|synthetic_column/)
            act(() => logic.actions.loadData())
            expect(capture.mock.calls.filter(([event]) => event === 'customer_journey_finished')).toHaveLength(1)
            await act(async () => {
                await Promise.resolve()
                resolve({
                    results: results.map((row) => [...row]),
                    columns: ['synthetic_column'],
                    types: ['String'],
                    hasMore: false,
                })
                await expectLogic(logic).toFinishAllListeners()
            })
            expect(
                capture.mock.calls.filter(
                    ([event, properties]) => event === 'customer_journey_finished' && properties.outcome === 'usable'
                )
            ).toHaveLength(2)

            view.unmount()
        }
    )

    it.each(['initial', 'subsequent'])('does not adopt the %s request made with the table hidden', async (request) => {
        personsSceneLogic.actions.setQuery({ ...personsSceneLogic.values.query, showResultsTable: false })
        const view = render(<PersonTable />)
        const logic = dataNodeLogic.findMounted({ key: 'person-journey-test' })!
        const fullRequests = (): number =>
            jest
                .mocked(performQuery)
                .mock.calls.filter(([query]) => isActorsQuery(query) && !query.select?.[0]?.startsWith('count(')).length
        expect(fullRequests()).toBe(1)
        expect(screen.queryByRole('table')).toBeNull()
        expect(capture).not.toHaveBeenCalled()
        if (request === 'subsequent') {
            await act(async () => {
                resolve({ results: [], columns: [], types: [], hasMore: false })
                await expectLogic(logic).toFinishAllListeners()
                const query = personsSceneLogic.values.query
                if (!isActorsQuery(query.source)) {
                    throw new Error('Expected the Persons ActorsQuery source')
                }
                personsSceneLogic.actions.setQuery({
                    ...query,
                    source: { ...query.source, search: 'synthetic-hidden-search' },
                })
                await Promise.resolve()
            })
        }
        expect(fullRequests()).toBe(request === 'subsequent' ? 2 : 1)
        const requestsBeforeReveal = fullRequests()
        act(() => personsSceneLogic.actions.setQuery({ ...personsSceneLogic.values.query, showResultsTable: true }))
        await act(async () => {
            resolve({ results: [], columns: [], types: [], hasMore: false })
            await expectLogic(logic).toFinishAllListeners()
        })
        expect(screen.getByRole('table')).toBeTruthy()
        expect(fullRequests()).toBe(requestsBeforeReveal)
        expect(capture).not.toHaveBeenCalled()
        view.unmount()
    })

    it('stops a visible in-flight request when hidden and does not revive it on reveal', async () => {
        const view = render(<PersonTable />)
        const logic = dataNodeLogic.findMounted({ key: 'person-journey-test' })!
        expect(capture.mock.calls).toEqual([
            ['customer_journey_started', expect.objectContaining({ journey_name: 'person_search' })],
        ])
        act(() => personsSceneLogic.actions.setQuery({ ...personsSceneLogic.values.query, showResultsTable: false }))
        expect(capture.mock.calls.at(-1)?.[1]).toMatchObject({ outcome: 'observation_stopped' })
        act(() => personsSceneLogic.actions.setQuery({ ...personsSceneLogic.values.query, showResultsTable: true }))
        await act(async () => {
            resolve({ results: [], columns: [], types: [], hasMore: false })
            await expectLogic(logic).toFinishAllListeners()
        })
        expect(screen.getByRole('table')).toBeTruthy()
        expect(capture.mock.calls).toHaveLength(2)
        expect(capture.mock.calls.at(-1)?.[1]).not.toHaveProperty('first_useful_ms')
        view.unmount()
    })

    it.each(['disabled', 'capture failure'])('preserves query results when telemetry is %s', async (state) => {
        jest.mocked(journeyStarter.startCustomerJourney).mockImplementation(() => {
            if (state === 'capture failure') {
                throw new Error('synthetic capture failure')
            }
            return null
        })
        const view = render(<PersonTable />)
        const logic = dataNodeLogic.findMounted({ key: 'person-journey-test' })!
        await act(async () => {
            resolve({ results: [], columns: [], types: [], hasMore: false })
            await expectLogic(logic).toFinishAllListeners()
        })
        expect(logic.values.response).toMatchObject({ results: [] })
        expect(logic.values.responseError).toBeNull()
        expect(capture).not.toHaveBeenCalled()
        view.unmount()
    })

    it('stops when the table unmounts even though attached logic remains mounted', () => {
        const view = render(<PersonTable />)
        view.unmount()
        expect(dataNodeLogic.findMounted({ key: 'person-journey-test' })).toBeTruthy()
        expect(capture.mock.calls.at(-1)?.[1].outcome).toBe('observation_stopped')
    })

    it('debounces typing before request dispatch and does not start for count or pagination', async () => {
        const view = render(<PersonTable />)
        const logic = dataNodeLogic.findMounted({ key: 'person-journey-test' })!
        await act(async () => {
            resolve({ results: [], columns: [], types: [], hasMore: false })
            await expectLogic(logic).toFinishAllListeners()
        })
        const starts = (): number => capture.mock.calls.filter(([event]) => event === 'customer_journey_started').length
        ;(performQuery as jest.Mock).mockResolvedValue({ results: [], columns: [], types: [], hasMore: false })
        jest.useFakeTimers()
        const input = screen.getByPlaceholderText('Search by name, email, Person ID or Distinct ID')
        fireEvent.change(input, { target: { value: 'synthetic-search-a' } })
        act(() => jest.advanceTimersByTime(150))
        fireEvent.change(input, { target: { value: 'synthetic-search-b' } })
        act(() => jest.advanceTimersByTime(299))
        expect(starts()).toBe(1)
        await act(async () => {
            jest.advanceTimersByTime(1)
            await Promise.resolve()
        })
        expect(starts()).toBe(2)
        await act(async () => {
            logic.actions.loadNextData()
            logic.actions.loadFilteredCount()
            jest.advanceTimersByTime(300)
            await Promise.resolve()
        })
        jest.useRealTimers()
        expect(starts()).toBe(2)
        expect(JSON.stringify(capture.mock.calls)).not.toContain('synthetic-search')
        view.unmount()
    })

    it.each([
        { kind: NodeKind.GroupsQuery, group_type_index: 0 } as const,
        { kind: NodeKind.ActorsQuery, source: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' } } as const,
    ])('excludes unsupported person-source shape %j', (query) => {
        expect(getPersonSearchJourney({ kind: NodeKind.DataTableNode, source: query })).toBeUndefined()
    })
})
