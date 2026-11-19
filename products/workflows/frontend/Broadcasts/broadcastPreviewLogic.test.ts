import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import schema from '~/queries/schema.json'
import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { DEFAULT_BROADCAST_EMAIL, broadcastWizardLogic } from './broadcastWizardLogic'

const PRO_PLAN: AnyPropertyFilter[] = [
    { key: 'plan', value: ['pro'], operator: PropertyOperator.Exact, type: PropertyFilterType.Person },
]
const HAS_EMAIL = { key: 'email', type: 'person', operator: 'is_set', value: 'is_set' }
const ADA = ['person-ada', { display_name: 'Ada' }, JSON.stringify({ email: 'ada@example.com', name: 'Ada' })]
const GRACE = ['person-grace', { display_name: 'Grace' }, JSON.stringify({ email: 'grace@example.com', name: 'Grace' })]
const NO_EMAIL = ['person-anon', { display_name: 'Anon' }, JSON.stringify({ name: 'Anon' })]
const NO_EMAIL_EITHER = ['person-bo', { display_name: 'Bo' }, JSON.stringify({ name: 'Bo' })]
const SAVED_DRAFT = {
    id: 'broadcast-1',
    status: 'draft',
    actions: [{ id: 'trigger_node', type: 'trigger', config: { type: 'batch', filters: { properties: PRO_PLAN } } }],
}

const ACCEPTED_FILTER_KEYS: Record<string, string[]> = {
    cohort: Object.keys(schema.definitions.CohortPropertyFilter.properties),
    person: Object.keys(schema.definitions.PersonPropertyFilter.properties),
}
const savedCondition = (filter: Record<string, unknown>, negation: boolean): Record<string, unknown> => ({
    ...filter,
    negation,
    bytecode: ['_H', 1, 29],
    conditionHash: 'hash',
})
const savedBroadcast = (properties: Record<string, unknown>[]): Record<string, unknown> => ({
    id: 'broadcast-1',
    status: 'draft',
    actions: [{ id: 'trigger_node', type: 'trigger', config: { type: 'batch', filters: { properties } } }],
})

describe('broadcastPreviewLogic', () => {
    let wizard: ReturnType<typeof broadcastWizardLogic.build>
    let logic: ReturnType<typeof broadcastPreviewLogic.build>
    let query: jest.SpyInstance

    const mountWith = async (rows: any[][] | undefined): Promise<void> => {
        query.mockResolvedValue({ results: rows })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPersonsSuccess'])
    }

    beforeEach(() => {
        useMocks({
            get: { '/api/projects/:team_id/integrations/': { results: [], count: 0 } },
            post: { '/api/projects/:team_id/hog_flows/user_blast_radius/': () => [200, { affected: 0, total: 0 }] },
        })
        initKeaTests()
        query = jest.spyOn(api, 'query')
        wizard = broadcastWizardLogic({ id: 'new' })
        wizard.mount()
        logic = broadcastPreviewLogic({ id: 'new' })
    })

    afterEach(() => {
        logic.unmount()
        wizard.unmount()
        jest.restoreAllMocks()
        resumeKeaLoadersErrors()
    })

    it('looks up preview people in the audience on mount and again when the audience changes', async () => {
        await mountWith([ADA])
        wizard.actions.setAudienceProperties(PRO_PLAN)
        await expectLogic(logic).toDispatchActions(['loadPersons', 'loadPersonsSuccess'])

        expect(query.mock.calls.map(([sent]) => sent)).toEqual(
            [[HAS_EMAIL], [...PRO_PLAN, HAS_EMAIL]].map((properties) => ({
                kind: NodeKind.ActorsQuery,
                tags: { productKey: ProductKey.WORKFLOWS },
                properties,
                select: ['id', 'person_display_name -- Person', 'properties'],
                limit: 25,
            }))
        )
    })

    it('looks up preview people in the audience a saved draft resumes with', async () => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/:id/': () => [200, SAVED_DRAFT] } })
        query.mockImplementation(async (sent: any) => ({ results: sent.properties.length ? [ADA] : [NO_EMAIL] }))
        wizard.unmount()
        wizard = broadcastWizardLogic({ id: 'broadcast-1' })
        wizard.mount()
        logic = broadcastPreviewLogic({ id: 'broadcast-1' })
        logic.mount()
        await waitFor(() => expect(logic.values.persons.map((person) => person.id)).toEqual(['person-ada']))
        expect(query.mock.lastCall?.[0].properties).toEqual(PRO_PLAN)
    })

    describe('a saved broadcast with a cohort audience', () => {
        let saved: Record<string, unknown>[]
        let received: Record<string, unknown>[][]

        beforeEach(() => {
            received = []
            useMocks({
                get: { '/api/projects/:team_id/hog_flows/:id/': () => [200, savedBroadcast(saved)] },
                post: {
                    '/api/environments/:team_id/query/:kind': async ({ request }) => {
                        const sent: Record<string, unknown>[] = ((await request.json()) as any).query.properties
                        received.push(sent)
                        const rejected = sent.flatMap((filter) =>
                            Object.keys(filter).filter(
                                (key) => !ACCEPTED_FILTER_KEYS[String(filter.type)]?.includes(key)
                            )
                        )
                        return rejected.length
                            ? [400, { type: 'validation_error', detail: `Extra inputs: ${rejected.join(', ')}` }]
                            : [200, { results: sent.length ? [ADA] : [] }]
                    },
                },
            })
        })

        const resume = async (properties: Record<string, unknown>[]): Promise<void> => {
            saved = properties
            silenceKeaLoadersErrors()
            wizard.unmount()
            wizard = broadcastWizardLogic({ id: 'broadcast-1' })
            wizard.mount()
            logic = broadcastPreviewLogic({ id: 'broadcast-1' })
            logic.mount()
        }
        const previewPeople = (): string[] => logic.values.persons.map((person) => person.id)

        const COHORT = { key: 'id', type: 'cohort', value: 42, operator: 'in' }
        const PRO = { key: 'plan', type: 'person', value: ['pro'], operator: 'exact' }

        it.each([
            [
                'an included cohort and sends it to the query as in',
                [savedCondition(COHORT, false), savedCondition(PRO, false)],
                [COHORT, PRO],
            ],
            [
                'an excluded cohort and sends it to the query as not_in',
                [savedCondition(COHORT, true), savedCondition(PRO, false)],
                [{ ...COHORT, operator: 'not_in' }, PRO],
            ],
        ])('loads preview people for %s', async (_name, conditions, sent) => {
            await resume(conditions)

            await waitFor(() => expect(previewPeople()).toEqual(['person-ada']))
            expect(received.at(-1)).toEqual([...sent, HAS_EMAIL])
        })
    })

    it.each([
        [
            'the display name',
            [7, { display_name: 'Ada' }, '{"email":"ada@example.com"}'],
            'Ada',
            { email: 'ada@example.com' },
        ],
        [
            'the email without a display name',
            ['p', {}, '{"email":"ada@example.com"}'],
            'ada@example.com',
            { email: 'ada@example.com' },
        ],
        ['the id without a name or email', ['p', null, '{"name":"Ada"}'], 'p', { name: 'Ada' }],
        [
            'properties already parsed',
            ['p', null, { email: 'ada@example.com' }],
            'ada@example.com',
            { email: 'ada@example.com' },
        ],
        ['unreadable properties', ['p', null, '{not json'], 'p', {}],
        ['missing properties', ['p', null, null], 'p', {}],
    ])('names a preview person by %s', async (_name, row, displayName, properties) => {
        await mountWith([row])

        expect(logic.values.persons).toEqual([{ id: String(row[0]), displayName, properties }])
    })

    it('shows no one when the query returns no results', async () => {
        await mountWith(undefined)

        expect(logic.values).toMatchObject({ persons: [], previewPerson: null, personsFailed: false })
    })

    it.each([
        ['the person the sender picked', [ADA, NO_EMAIL], 'person-anon', 'person-anon'],
        ['the first person with an email', [NO_EMAIL, ADA, GRACE], null, 'person-ada'],
        ['the first person when nobody has an email', [NO_EMAIL, NO_EMAIL_EITHER], null, 'person-anon'],
        ['a reachable person when the pick left the audience', [NO_EMAIL, ADA], 'person-gone', 'person-ada'],
    ])('previews %s', async (_name, rows, picked, expected) => {
        await mountWith(rows)
        logic.actions.selectPerson(picked)

        expect(logic.values.previewPerson?.id).toBe(expected)
    })

    it.each([
        ['a new audience', PRO_PLAN],
        ['the same audience applied again', []],
    ])('drops the pick when %s reloads the people', async (_name, audience) => {
        await mountWith([NO_EMAIL, ADA])
        logic.actions.selectPerson('person-anon')
        await expectLogic(logic, () => wizard.actions.setAudienceProperties([...audience])).toDispatchActions([
            'loadPersonsSuccess',
        ])

        expect(logic.values.selectedPersonId).toBeNull()
        expect(logic.values.previewPerson?.id).toBe('person-ada')
    })

    it('tells a failed lookup apart from an empty audience until a reload succeeds', async () => {
        silenceKeaLoadersErrors()
        query.mockRejectedValueOnce(new Error('query failed'))
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPersonsFailure'])
        expect(logic.values).toMatchObject({ persons: [], personsFailed: true, personsLoading: false })

        let respond: (value: unknown) => void = () => {}
        query.mockReturnValueOnce(new Promise((resolve) => (respond = resolve)))
        logic.actions.loadPersons()
        expect(logic.values).toMatchObject({ personsFailed: false, personsLoading: true })

        respond({ results: [ADA] })
        await expectLogic(logic).toDispatchActions(['loadPersonsSuccess'])
        expect(logic.values).toMatchObject({ personsFailed: false, personsLoading: false })
    })

    it('keeps loading when a replaced lookup fails after a newer one starts', async () => {
        await mountWith([ADA])
        silenceKeaLoadersErrors()
        let rejectOld: (error: Error) => void = () => {}
        let resolveNew: (value: unknown) => void = () => {}
        query
            .mockReturnValueOnce(new Promise((_, reject) => (rejectOld = reject)))
            .mockReturnValueOnce(new Promise((resolve) => (resolveNew = resolve)))
        logic.actions.loadPersons()
        await waitFor(() => expect(query).toHaveBeenCalledTimes(2))
        logic.actions.loadPersons()
        await waitFor(() => expect(query).toHaveBeenCalledTimes(3))

        rejectOld(new Error('query failed'))
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(logic.values).toMatchObject({ personsLoading: true, personsFailed: false })

        resolveNew({ results: [GRACE] })
        await expectLogic(logic).toDispatchActions(['loadPersonsSuccess'])
        expect(logic.values.persons.map((person) => person.id)).toEqual(['person-grace'])
    })

    it('re-renders the email and push merge tags when the person or the message changes', async () => {
        await mountWith([ADA, GRACE])
        const write = (word: string): void => {
            const tag = '{{ person.properties.name }}'
            wizard.actions.setEmail({
                ...DEFAULT_BROADCAST_EMAIL,
                to: { email: `${word} {{ person.properties.email }}` },
                subject: `${word} subject ${tag}`,
                html: `<p>${word} html ${tag}</p>`,
                text: `${word} text ${tag}`,
            })
            wizard.actions.setPush({ channels: [], title: `${word} title ${tag}`, body: `${word} body ${tag}` })
        }
        const rendered = (word: string, name: string): Record<string, string> => ({
            previewTo: `${word} ${name.toLowerCase()}@example.com`,
            previewSubject: `${word} subject ${name}`,
            previewHtml: `<p>${word} html ${name}</p>`,
            previewText: `${word} text ${name}`,
            previewPushTitle: `${word} title ${name}`,
            previewPushBody: `${word} body ${name}`,
        })
        write('First')
        expect(logic.values).toMatchObject(rendered('First', 'Ada'))

        logic.actions.selectPerson('person-grace')
        expect(logic.values).toMatchObject(rendered('First', 'Grace'))

        write('Second')
        expect(logic.values).toMatchObject(rendered('Second', 'Grace'))
    })

    it('previews an empty recipient when the email has none', async () => {
        await mountWith([ADA])
        wizard.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, to: undefined as any })

        expect(logic.values.previewTo).toBe('')
    })
})
