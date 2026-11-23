import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { BindingApi } from './generated/api.schemas'
import { managedEntityLogic } from './managedEntityLogic'
import { managedKindsLogic } from './managedKindsLogic'

const FLAG_BINDING: BindingApi = {
    id: '0b6f8f3e-0000-4000-8000-000000000001',
    stack_name: 'web-app',
    repository: 'example-org/web-app',
    kind: 'flag',
    key: 'checkout-v2',
    entity_id: '42',
    entity_url: null,
    source: { file: '.ph/flags.ts', export: 'checkoutV2' },
    status: 'bound',
    owned_fields: ['key', 'name', 'tags'],
}

describe('managedEntityLogic', () => {
    let kindsRequests = 0
    let lookups: string[]
    let detaches: string[]

    const useStackMocks = (managedKinds: string[]): void => {
        useMocks({
            get: {
                '/api/projects/:team_id/stacks/managed_kinds/': () => {
                    kindsRequests += 1
                    return [
                        200,
                        {
                            results: managedKinds.map((kind) => ({
                                kind,
                                stack_name: 'web-app',
                                repository: 'example-org/web-app',
                                definitions: 1,
                                redirect_creates: false,
                            })),
                        },
                    ]
                },
                '/api/projects/:team_id/stacks/bindings/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    lookups.push(`${params.get('kind')}/${params.get('entity_id')}`)
                    const found = params.get('kind') === 'flag' && params.get('entity_id') === '42'
                    return [200, { binding: found ? FLAG_BINDING : null }]
                },
            },
            post: {
                '/api/projects/:team_id/stacks/:name/bindings/:id/detach/': ({ params }) => {
                    detaches.push(`${params.name}/${params.id}`)
                    return [200, { ...FLAG_BINDING, status: 'detached' }]
                },
            },
        })
    }

    const enableFlag = (): void => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.POSTHOG_AS_CODE], {
            [FEATURE_FLAGS.POSTHOG_AS_CODE]: true,
        })
    }

    beforeEach(() => {
        kindsRequests = 0
        lookups = []
        detaches = []
        initKeaTests()
    })

    it('asks nothing at all while the feature flag is off', async () => {
        useStackMocks(['flag'])
        const logic = managedEntityLogic({ kind: 'flag', entityId: 42 })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ managedState: 'unmanaged' })
        expect(kindsRequests).toBe(0)
        expect(lookups).toEqual([])
    })

    it('looks up no entity in a project where no stack manages the kind', async () => {
        enableFlag()
        useStackMocks(['dashboard'])
        const first = managedEntityLogic({ kind: 'flag', entityId: 42 })
        const second = managedEntityLogic({ kind: 'flag', entityId: 43 })
        first.mount()
        await expectLogic(managedKindsLogic).toDispatchActions(['loadManagedKindsSuccess'])
        second.mount()

        await expectLogic(first).toFinishAllListeners().toMatchValues({ managedState: 'unmanaged', binding: null })
        await expectLogic(second).toFinishAllListeners().toMatchValues({ managedState: 'unmanaged' })
        expect(kindsRequests).toBe(1)
        expect(lookups).toEqual([])
    })

    it('looks up a managed kind once and answers which fields code owns', async () => {
        enableFlag()
        useStackMocks(['flag'])
        const logic = managedEntityLogic({ kind: 'flag', entityId: 42 })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['lookUpBindingSuccess']).toMatchValues({
            managedState: 'managed',
            binding: FLAG_BINDING,
        })
        expect(lookups).toEqual(['flag/42'])
        expect(logic.values.ownedFieldDisabledReason('key')).toBe('Managed in code. Edit .ph/flags.ts to change this.')
        expect(logic.values.ownedFieldDisabledReason('tags')).not.toBeNull()
        expect(logic.values.ownedFieldDisabledReason('filters')).toBeNull()
        expect(logic.values.ownedFieldDisabledReason('active')).toBeNull()

        const otherFlag = managedEntityLogic({ kind: 'flag', entityId: 7 })
        otherFlag.mount()
        await expectLogic(otherFlag).toFinishAllListeners().toMatchValues({ managedState: 'unmanaged' })
        expect(kindsRequests).toBe(1)
        expect(lookups).toEqual(['flag/42', 'flag/7'])
    })

    it('looks up a natural-key kind once, by the name its binding key holds', async () => {
        enableFlag()
        useStackMocks(['event'])
        const logic = managedEntityLogic({
            kind: 'event',
            entityId: '0190a3c4-0000-7000-8000-000000000001',
            naturalId: 'checkout_completed',
        })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['lookUpBindingSuccess'])
        expect(lookups).toEqual(['event/checkout_completed'])
    })

    it('releases every field once detached', async () => {
        enableFlag()
        useStackMocks(['flag'])
        const logic = managedEntityLogic({ kind: 'flag', entityId: 42 })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['lookUpBindingSuccess'])

        await expectLogic(logic, () => {
            logic.actions.detach()
        })
            .toDispatchActions(['detachSuccess'])
            .toMatchValues({ managedState: 'unmanaged', isManaged: false, detaching: false })
        expect(detaches).toEqual([`web-app/${FLAG_BINDING.id}`])
        expect(logic.values.ownedFieldDisabledReason('key')).toBeNull()
    })
})
