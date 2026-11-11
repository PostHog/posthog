import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { MessageAsset } from './messageAssetsApi'
import { WorkflowAssetsLogicProps, workflowAssetsLogic } from './workflowAssetsLogic'

const RECIPIENTS = ['ada@example.com', 'bob@example.com']

describe('workflowAssetsLogic', () => {
    let received: Record<string, string>[]
    let failNextLoad: boolean

    beforeEach(() => {
        received = []
        failNextLoad = false
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/assets/': ({ request, params }) => {
                    const query = Object.fromEntries(new URL(request.url).searchParams)
                    received.push(query)
                    if (failNextLoad) {
                        return [500, { detail: 'Assets are unavailable.' }]
                    }
                    const rows: Partial<MessageAsset>[] = RECIPIENTS.filter((recipient) =>
                        recipient.includes(query.search ?? '')
                    ).map((recipient) => ({
                        function_id: params.id as string,
                        parent_run_id: query.parent_run_id ?? '',
                        action_id: query.action_id ?? 'email_node',
                        invocation_id: query.invocation_id ?? `inv-${recipient}`,
                        recipient,
                    }))
                    return [200, rows]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    const loaded = async (props: WorkflowAssetsLogicProps): Promise<ReturnType<typeof workflowAssetsLogic.build>> => {
        const logic = workflowAssetsLogic(props)
        logic.mount()
        await logic.asyncActions.loadAssets()
        return logic
    }

    it.each([
        ['every email the workflow sent', {}, {}],
        [
            'the emails of one batch run, step and invocation',
            { parentRunId: 'run-1', actionId: 'email_2', invocationId: 'inv-9' },
            { parent_run_id: 'run-1', action_id: 'email_2', invocation_id: 'inv-9' },
        ],
    ])('lists %s', async (_name, scope, expectedQuery) => {
        const logic = await loaded({ id: 'wf-1', ...scope })

        expect(received).toEqual([expectedQuery])
        expect(logic.values.assetsLoading).toBe(false)
        expect(logic.values.assets.map((asset) => [asset.function_id, asset.recipient])).toEqual([
            ['wf-1', 'ada@example.com'],
            ['wf-1', 'bob@example.com'],
        ])
    })

    it.each(['parentRunId', 'actionId', 'invocationId'] as const)(
        'keeps two tables that differ only in %s apart',
        async (prop) => {
            const first = await loaded({ id: 'wf-1', [prop]: 'one' })
            const second = await loaded({ id: 'wf-1', [prop]: 'two' })

            const scopeOf = (asset: MessageAsset): string[] => [
                asset.parent_run_id,
                asset.action_id,
                asset.invocation_id,
            ]
            expect(first.values.assets.map(scopeOf)).not.toEqual(second.values.assets.map(scopeOf))
        }
    )

    it('lists nothing for a workflow that is not saved yet', async () => {
        const logic = await loaded({ id: 'new' })

        expect(logic.values.assets).toEqual([])
    })

    it('searches once the person stops typing', async () => {
        // A logic key that an earlier test already built registers its listeners twice after initKeaTests,
        // so both keystrokes would send a request. A fresh id keeps one listener.
        const logic = await loaded({ id: 'wf-search' })
        received = []
        jest.useFakeTimers()

        logic.actions.setSearch('a')
        await jest.advanceTimersByTimeAsync(200)
        logic.actions.setSearch('ada')
        await jest.advanceTimersByTimeAsync(249)
        expect(received).toEqual([])

        await jest.advanceTimersByTimeAsync(1)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        expect(received.map((query) => query.search)).toEqual(['ada'])
        expect(logic.values.assets.map((asset) => asset.recipient)).toEqual(['ada@example.com'])
    })

    it('keeps the listed emails and stops loading when a reload fails', async () => {
        const logic = await loaded({ id: 'wf-1' })
        failNextLoad = true

        await logic.asyncActions.loadAssets().catch(() => undefined)

        expect(logic.values.assetsLoading).toBe(false)
        expect(logic.values.assets.map((asset) => asset.recipient)).toEqual(RECIPIENTS)
    })

    it('opens an email in the viewer from its own content url, and closes it', async () => {
        const logic = await loaded({ id: 'wf-1' })
        const [email] = logic.values.assets

        logic.actions.openAsset(email)
        expect(logic.values.selectedAsset).toEqual(email)
        expect(logic.values.contentUrl(email)).toMatch(
            /\/api\/projects\/\d+\/hog_flows\/wf-1\/assets\/content\?invocation_id=inv-ada%40example\.com&action_id=email_node$/
        )

        logic.actions.closeAsset()
        expect(logic.values.selectedAsset).toBeNull()
    })
})
