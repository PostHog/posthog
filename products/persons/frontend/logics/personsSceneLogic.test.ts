import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { PEOPLE_LIST_DEFAULT_QUERY, isPeopleListDefaultQuery, personsSceneLogic } from './personsSceneLogic'

const blankScene = (): any => ({ scene: { component: () => null, logic: null } })
const scenes: any = { [Scene.Persons]: blankScene }

describe('personsSceneLogic', () => {
    let logic: ReturnType<typeof personsSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        sceneLogic({ scenes }).mount()
        logic = personsSceneLogic()
        logic.mount()
    })

    it.each([
        ['the persons list', urls.persons(), true],
        ['a new insight', urls.insightNew({ query: PEOPLE_LIST_DEFAULT_QUERY }), false],
        ['a person profile', urls.personByUUID('00000000-0000-0000-0000-000000000001'), false],
    ])('syncs query changes to the URL only on the persons list: %s', async (_, destination, syncsQuery) => {
        router.actions.push(urls.persons())
        router.actions.push(destination)
        await expectLogic(logic).toFinishAllListeners()

        const location = router.values.location
        const query: DataTableNode = {
            ...PEOPLE_LIST_DEFAULT_QUERY,
            source: { kind: NodeKind.ActorsQuery, select: ['person', 'person.created_at'] },
        }

        await expectLogic(logic, () => logic.actions.setQuery(query)).toFinishAllListeners()

        expect(logic.values.query).toEqual(query)
        if (syncsQuery) {
            expect(router.values.location.pathname).toEqual(addProjectIdIfMissing(urls.persons()))
            expect(router.values.hashParams.q).toEqual(query)

            await expectLogic(logic, () => logic.actions.setQuery(logic.values.defaultQuery)).toFinishAllListeners()
            expect(router.values.hashParams.q).toBeUndefined()
        } else {
            expect(router.values.location).toEqual(location)
        }
    })

    describe('query reducer', () => {
        it('starts with default query', () => {
            expectLogic(logic).toMatchValues({
                query: PEOPLE_LIST_DEFAULT_QUERY,
            })
        })

        it('setQuery preserves defaultColumns even when custom query omits them', () => {
            const customQuery: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.ActorsQuery,
                    select: ['person', 'person.created_at'],
                },
                full: true,
            }

            logic.actions.setQuery(customQuery)

            expectLogic(logic).toMatchValues({
                query: expect.objectContaining({
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.ActorsQuery,
                        select: ['person', 'person.created_at'],
                    },
                    full: true,
                    defaultColumns: PEOPLE_LIST_DEFAULT_QUERY.defaultColumns,
                }),
            })
        })

        it('setQuery replaces previous query state', () => {
            const query1 = {
                ...PEOPLE_LIST_DEFAULT_QUERY,
                source: { ...PEOPLE_LIST_DEFAULT_QUERY.source, select: ['person'] },
            }
            const query2 = {
                ...PEOPLE_LIST_DEFAULT_QUERY,
                source: { ...PEOPLE_LIST_DEFAULT_QUERY.source, select: ['person', 'person.created_at'] },
            }

            logic.actions.setQuery(query1)
            logic.actions.setQuery(query2)

            expectLogic(logic).toMatchValues({
                query: expect.objectContaining({
                    source: expect.objectContaining({
                        select: ['person', 'person.created_at'],
                    }),
                }),
            })
        })
    })

    it.each<{ search: string; url: string; searchParams?: Record<string, string> }>([
        // The shape navigateToHref pushes, which keeps the search as text.
        { search: 'acme', url: urls.persons(), searchParams: { search: 'acme' } },
        { search: '001234', url: urls.persons(), searchParams: { search: '001234' } },
        // A reload or a pasted link, where the router reads `0` as a number.
        { search: '0', url: `${urls.persons()}?search=0` },
    ])('fills the search from a search param of $search in the URL', async ({ search, url, searchParams }) => {
        router.actions.push(url, searchParams)

        await expectLogic(logic).toMatchValues({
            query: expect.objectContaining({
                source: { ...PEOPLE_LIST_DEFAULT_QUERY.source, search },
            }),
        })
    })

    describe('boolean reducers', () => {
        it.each([
            { action: 'setShowDisplayNameNudge', field: 'showDisplayNameNudge' },
            { action: 'setIsBannerLoading', field: 'isBannerLoading' },
        ])('$field starts false and toggles via $action', ({ action, field }) => {
            expectLogic(logic).toMatchValues({ [field]: false })

            const act = logic.actions[action as 'setShowDisplayNameNudge' | 'setIsBannerLoading']

            act(true)
            expectLogic(logic).toMatchValues({ [field]: true })

            act(false)
            expectLogic(logic).toMatchValues({ [field]: false })
        })
    })

    describe('isPeopleListDefaultQuery', () => {
        const defaultSelect = [...defaultDataTableColumns(NodeKind.ActorsQuery, false), 'person.$delete']
        const lastSeenAtSelect = [...defaultDataTableColumns(NodeKind.ActorsQuery, true), 'person.$delete']

        it.each<[string, string[], boolean]>([
            ['the default columns', defaultSelect, true],
            ['the default columns for a team that tracks last seen at', lastSeenAtSelect, true],
            ['an extra column the user added', [...defaultSelect, 'pdi.distinct_id'], false],
            ['a narrower set of columns', ['id'], false],
        ])('%s', (_label, select, expected) => {
            expect(isPeopleListDefaultQuery({ ...PEOPLE_LIST_DEFAULT_QUERY.source, select })).toBe(expected)
        })
    })
})
