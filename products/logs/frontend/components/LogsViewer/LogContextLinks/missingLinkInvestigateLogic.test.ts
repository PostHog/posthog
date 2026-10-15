import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'
import { maxMocks } from 'scenes/max/testUtils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { missingLinkInvestigateLogic } from './missingLinkInvestigateLogic'
import { MissingLinkEventContext } from './missingLinkTelemetry'

const eventContext: MissingLinkEventContext = { missing: ['trace'], source: 'log-drawer', service_name: 'checkout-api' }

describe('missingLinkInvestigateLogic', () => {
    let logic: ReturnType<typeof missingLinkInvestigateLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.setSidePanelAvailable(true)
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).mount()
        logic = missingLinkInvestigateLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).unmount()
    })

    test.each([
        { name: 'new view, no rail', flags: [FEATURE_FLAGS.PHAI_SANDBOX_MODE], startsTask: true },
        {
            name: 'new view, rail',
            flags: [FEATURE_FLAGS.PHAI_SANDBOX_MODE, FEATURE_FLAGS.TODAY_RAIL_NAV],
            startsTask: true,
        },
        { name: 'legacy view, no rail', flags: [], startsTask: false },
        { name: 'legacy view, rail', flags: [FEATURE_FLAGS.TODAY_RAIL_NAV], startsTask: false },
    ])('$name offers a side panel task only when the panel can start one', ({ flags, startsTask }) => {
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))

        expect(logic.values.startsSidePanelTask).toBe(startsTask)
    })

    test('starts the task in the side panel and records the route', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PHAI_SANDBOX_MODE], {
            [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
        })
        router.actions.push('/logs')
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)

        await expectLogic(logic, () => {
            logic.actions.startTask('Find the missing session ID', () => {}, eventContext)
        }).toFinishAllListeners()

        expect(capture.mock.calls.filter(([event]) => event.startsWith('logs missing link'))).toEqual([
            [
                'logs missing link investigate clicked',
                { ...eventContext, option: 'posthog-ai-task', route: 'side-panel-task' },
            ],
        ])
        capture.mockRestore()
        expect({
            seeded: composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed?.prompt ?? null,
            sidePanelTab: sidePanelStateLogic.values.sidePanelOpen ? sidePanelStateLogic.values.selectedTab : null,
            path: removeProjectIdIfPresent(router.values.location.pathname),
        }).toEqual({ seeded: 'Find the missing session ID', sidePanelTab: SidePanelTab.Max, path: '/logs' })
    })
})
