import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { DEFAULT_BROADCAST_EMAIL, broadcastWizardLogic } from './broadcastWizardLogic'

const PRO_PLAN: AnyPropertyFilter[] = [
    { key: 'plan', value: ['pro'], operator: PropertyOperator.Exact, type: PropertyFilterType.Person },
]
const ADA = ['person-ada', { display_name: 'Ada' }, JSON.stringify({ email: 'ada@example.com', name: 'Ada' })]
const GRACE = ['person-grace', { display_name: 'Grace' }, JSON.stringify({ email: 'grace@example.com', name: 'Grace' })]
const NO_EMAIL = ['person-anon', { display_name: 'Anon' }, JSON.stringify({ name: 'Anon' })]
const NO_EMAIL_EITHER = ['person-bo', { display_name: 'Bo' }, JSON.stringify({ name: 'Bo' })]
const SAVED_DRAFT = {
    id: 'broadcast-1',
    status: 'draft',
    actions: [{ id: 'trigger_node', type: 'trigger', config: { type: 'batch', filters: { properties: PRO_PLAN } } }],
}

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
            [[], PRO_PLAN].map((properties) => ({
                kind: NodeKind.ActorsQuery,
                tags: { productKey: ProductKey.WORKFLOWS, scene: Scene.Broadcast },
                properties,
                select: ['id', 'person_display_name -- Person', 'properties'],
                limit: 25,
            }))
        )
    })

    it('looks up preview people in the audience a saved draft resumes with', async () => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/:id/': () => [200, SAVED_DRAFT] } })
        query.mockResolvedValueOnce({ results: [NO_EMAIL] }).mockResolvedValue({ results: [ADA] })
        wizard.unmount()
        wizard = broadcastWizardLogic({ id: 'broadcast-1' })
        wizard.mount()
        logic = broadcastPreviewLogic({ id: 'broadcast-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPersonsSuccess', 'loadPersonsSuccess'])

        expect(query.mock.lastCall?.[0].properties).toEqual(PRO_PLAN)
        expect(logic.values.persons.map((person) => person.id)).toEqual(['person-ada'])
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

    it('drops the pick when the audience reloads', async () => {
        await mountWith([NO_EMAIL, ADA])
        logic.actions.selectPerson('person-anon')
        wizard.actions.setAudienceProperties(PRO_PLAN)
        await expectLogic(logic).toDispatchActions(['loadPersonsSuccess'])

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

    it('renders the email and push merge tags for the person the sender picked', async () => {
        await mountWith([ADA, GRACE])
        logic.actions.selectPerson('person-grace')
        const tag = '{{ person.properties.name }}'
        wizard.actions.setEmail({
            ...DEFAULT_BROADCAST_EMAIL,
            subject: `Subject ${tag}`,
            html: `<p>Html ${tag}</p>`,
            text: `Text ${tag}`,
        })
        wizard.actions.setPush({ channels: [], title: `Title ${tag}`, body: `Body ${tag}` })

        expect(logic.values).toMatchObject({
            previewTo: 'grace@example.com',
            previewSubject: 'Subject Grace',
            previewHtml: '<p>Html Grace</p>',
            previewText: 'Text Grace',
            previewPushTitle: 'Title Grace',
            previewPushBody: 'Body Grace',
        })
    })

    it('previews an empty recipient when the email has none', async () => {
        await mountWith([ADA])
        wizard.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, to: undefined as any })

        expect(logic.values.previewTo).toBe('')
    })
})
