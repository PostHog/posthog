import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER, MOCK_USER_UUID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PreflightStatus } from '~/types'

import { SubscriptionTargetEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { newSubscriptionTargetLogic } from './newSubscriptionTargetLogic'
import { subscriptionsSceneLogic, SubscriptionsTab } from './subscriptionsSceneLogic'

const EMPTY_SUBSCRIPTIONS = { count: 0, results: [] as unknown[] }

const blankScene = (): any => ({ scene: { component: () => null, logic: null } })
const scenes: any = { [Scene.Subscriptions]: blankScene }

function subscriptionListParamsFromUrl(url: string): URLSearchParams {
    return new URL(url).searchParams
}

describe('subscriptionsSceneLogic', () => {
    let logic: ReturnType<typeof subscriptionsSceneLogic.build>
    let subscriptionRequestUrls: string[]

    beforeEach(() => {
        subscriptionRequestUrls = []
        useMocks({
            get: {
                '/api/projects/:team_id/subscriptions/': ({ request }) => {
                    subscriptionRequestUrls.push(request.url)
                    return [200, EMPTY_SUBSCRIPTIONS]
                },
            },
        })
        initKeaTests()
        sceneLogic({ scenes }).mount()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        preflightLogic.actions.loadPreflightSuccess(preflightJson as unknown as PreflightStatus)
        router.actions.push(urls.subscriptions())
        logic = subscriptionsSceneLogic()
        logic.mount()
    })

    describe('list requests', () => {
        it('loads with default ordering -created_at', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('ordering')).toBe('-created_at')
            expect(params.get('limit')).toBe('20')
            expect(params.get('offset')).toBe('0')
        })

        it('sends resource_type=dashboard on Dashboard tab', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setCurrentTab(SubscriptionsTab.Dashboard)
            }).toDispatchActions(['setCurrentTab', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('resource_type')).toBe('dashboard')
        })

        it('sends resource_type=insight on Insight tab', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setCurrentTab(SubscriptionsTab.Insight)
            }).toDispatchActions(['setCurrentTab', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('resource_type')).toBe('insight')
        })

        it('sends resource_type=ai_prompt on AI reports tab', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: true,
            })
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: true })

            await expectLogic(logic, () => {
                logic.actions.setCurrentTab(SubscriptionsTab.AI)
            }).toDispatchActions(['setCurrentTab', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('resource_type')).toBe('ai_prompt')
        })

        it('ignores an AI reports URL when AI subscriptions are unavailable', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                router.actions.push(`${urls.subscriptions()}?tab=ai_prompt`)
            })
                .toFinishAllListeners()
                .toMatchValues({ currentTab: SubscriptionsTab.All })

            expect(subscriptionRequestUrls).toHaveLength(1)
            expect(subscriptionListParamsFromUrl(subscriptionRequestUrls[0]).has('resource_type')).toBe(false)
        })

        it('sends created_by for Mine tab', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setCurrentTab(SubscriptionsTab.Mine)
            }).toDispatchActions(['setCurrentTab', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('created_by')).toBe(MOCK_USER_UUID)
        })

        it('maps next delivery sorting to ordering query params', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setSubscriptionsSorting({ columnKey: 'next_delivery_date', order: 1 })
            }).toDispatchActions(['setSubscriptionsSorting', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            let params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('ordering')).toBe('next_delivery_date')

            subscriptionRequestUrls.length = 0
            await expectLogic(logic, () => {
                logic.actions.setSubscriptionsSorting({ columnKey: 'next_delivery_date', order: -1 })
            }).toDispatchActions(['setSubscriptionsSorting', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('ordering')).toBe('-next_delivery_date')
        })

        it('maps name, created by, and created sorting to ordering query params', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setSubscriptionsSorting({ columnKey: 'name', order: 1 })
            }).toDispatchActions(['setSubscriptionsSorting', 'loadSubscriptions', 'loadSubscriptionsSuccess'])
            expect(subscriptionListParamsFromUrl(subscriptionRequestUrls[0]).get('ordering')).toBe('title')

            subscriptionRequestUrls.length = 0
            await expectLogic(logic, () => {
                logic.actions.setSubscriptionsSorting({ columnKey: 'created_by', order: -1 })
            }).toDispatchActions(['setSubscriptionsSorting', 'loadSubscriptions', 'loadSubscriptionsSuccess'])
            expect(subscriptionListParamsFromUrl(subscriptionRequestUrls[0]).get('ordering')).toBe('-created_by__email')

            subscriptionRequestUrls.length = 0
            await expectLogic(logic, () => {
                logic.actions.setSubscriptionsSorting({ columnKey: 'created_at', order: 1 })
            }).toDispatchActions(['setSubscriptionsSorting', 'loadSubscriptions', 'loadSubscriptionsSuccess'])
            expect(subscriptionListParamsFromUrl(subscriptionRequestUrls[0]).get('ordering')).toBe('created_at')
        })

        it('reloads after deleteSubscriptionSuccess', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.deleteSubscriptionSuccess()
            }).toDispatchActions(['deleteSubscriptionSuccess', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
        })

        it('passes search to the list API after setSearch (debounced listener)', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setSearch('weekly')
            })
                .toFinishAllListeners()
                .toDispatchActions(['setSearch', 'loadSubscriptions', 'loadSubscriptionsSuccess'])
                .toMatchValues({ search: 'weekly' })

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('search')).toBe('weekly')
        })

        it('sends target_type when channel filter is set', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            subscriptionRequestUrls.length = 0

            await expectLogic(logic, () => {
                logic.actions.setTargetTypeFilter(SubscriptionTargetEnumApi.Slack)
            }).toDispatchActions(['setTargetTypeFilter', 'loadSubscriptions', 'loadSubscriptionsSuccess'])

            expect(subscriptionRequestUrls).toHaveLength(1)
            const params = subscriptionListParamsFromUrl(subscriptionRequestUrls[0])
            expect(params.get('target_type')).toBe('slack')
        })
    })

    describe('modal routing', () => {
        it('opens the modal on /subscriptions/new and closes when navigating back to the list', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])

            await expectLogic(logic, () => {
                router.actions.push(urls.subscriptionNew())
            }).toMatchValues({ subscriptionModalId: 'new' })

            await expectLogic(logic, () => {
                router.actions.push(urls.subscriptions())
            }).toMatchValues({ subscriptionModalId: null })
        })

        it.each([
            ['available', true, { kind: 'ai' }],
            ['unavailable', false, null],
        ])(
            'picks the AI report target from ?resource_type=ai_prompt when AI subscriptions are %s',
            async (_, aiAvailable, expectedTarget) => {
                await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
                organizationLogic.actions.loadCurrentOrganizationSuccess({
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: true,
                })
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: aiAvailable })
                const targetLogic = newSubscriptionTargetLogic()
                targetLogic.mount()

                await expectLogic(logic, () => {
                    router.actions.push(`${urls.subscriptionNew()}?resource_type=ai_prompt&prompt=What+changed`)
                }).toMatchValues({ subscriptionModalId: 'new' })

                expect(targetLogic.values.target).toEqual(expectedTarget)
                targetLogic.unmount()
            }
        )

        it('picks the AI report target once AI subscriptions become available after the deep link opened', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            const targetLogic = newSubscriptionTargetLogic()
            targetLogic.mount()

            await expectLogic(logic, () => {
                router.actions.push(`${urls.subscriptionNew()}?resource_type=ai_prompt`)
            }).toMatchValues({ subscriptionModalId: 'new' })
            expect(targetLogic.values.target).toBeNull()

            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: true,
            })
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: true })

            expect(targetLogic.values.target).toEqual({ kind: 'ai' })
            targetLogic.unmount()
        })

        it('drops the deep-linked target when AI subscriptions become unavailable while the modal is open', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: true,
            })
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: true })
            const targetLogic = newSubscriptionTargetLogic()
            targetLogic.mount()

            router.actions.push(`${urls.subscriptionNew()}?resource_type=ai_prompt`)
            expect(targetLogic.values.target).toEqual({ kind: 'ai' })

            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: false })
            expect(targetLogic.values.target).toBeNull()
            targetLogic.unmount()
        })

        it('keeps the chooser for an AI deep link on a self-hosted instance', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: true,
            })
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: true })
            preflightLogic.actions.loadPreflightSuccess({
                ...(preflightJson as unknown as PreflightStatus),
                cloud: false,
                is_debug: false,
            })
            const targetLogic = newSubscriptionTargetLogic()
            targetLogic.mount()

            await expectLogic(logic, () => {
                router.actions.push(`${urls.subscriptionNew()}?resource_type=ai_prompt`)
            }).toMatchValues({ subscriptionModalId: 'new', aiSubscriptionsAvailable: false })
            expect(targetLogic.values.target).toBeNull()
            targetLogic.unmount()
        })

        it('drops the deep-linked target when the list route closes the modal', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: true,
            })
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: true })
            const targetLogic = newSubscriptionTargetLogic()
            targetLogic.mount()

            router.actions.push(`${urls.subscriptionNew()}?resource_type=ai_prompt`)
            expect(targetLogic.values.target).toEqual({ kind: 'ai' })

            await expectLogic(logic, () => {
                router.actions.push(urls.subscriptions())
            }).toMatchValues({ subscriptionModalId: null })
            expect(targetLogic.values.target).toBeNull()

            router.actions.push(urls.subscriptionNew())
            expect(targetLogic.values.target).toBeNull()
            targetLogic.unmount()
        })

        it('opens the modal with the subscription id on /subscriptions/:id/edit', async () => {
            await expectLogic(logic).toDispatchActions(['loadSubscriptionsSuccess'])

            await expectLogic(logic, () => {
                router.actions.push(urls.subscriptionEdit('42'))
            }).toMatchValues({ subscriptionModalId: 42 })
        })
    })
})
