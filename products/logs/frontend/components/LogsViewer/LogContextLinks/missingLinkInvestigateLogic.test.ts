import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { maxMocks } from 'scenes/max/testUtils'
import { urls } from 'scenes/urls'

import { MAX_SIDE_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { missingLinkInvestigateLogic } from './missingLinkInvestigateLogic'
import { MissingLinkEventContext } from './missingLinkTelemetry'

jest.mock('lib/utils/newInternalTab')

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
        { name: 'new view, no rail', flags: [FEATURE_FLAGS.PHAI_SANDBOX_MODE], route: 'side-panel-task' },
        { name: 'legacy view, no rail', flags: [], route: 'legacy-ask' },
        {
            name: 'new view, rail',
            flags: [FEATURE_FLAGS.PHAI_SANDBOX_MODE, FEATURE_FLAGS.TODAY_RAIL_NAV],
            route: 'side-panel-task',
        },
        { name: 'legacy view, rail', flags: [FEATURE_FLAGS.TODAY_RAIL_NAV], route: 'ai-scene' },
    ])('$name sends the prompt to PostHog AI', async ({ flags, route }) => {
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        router.actions.push('/logs')
        ;(newInternalTab as jest.Mock).mockClear()
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)

        await expectLogic(logic, () => {
            logic.actions.startTask('Find the missing session ID', () => {}, eventContext)
        }).toFinishAllListeners()

        const seed = composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed
        expect(capture.mock.calls.filter(([event]) => event.startsWith('logs missing link'))).toEqual([
            ['logs missing link investigate clicked', { ...eventContext, option: 'posthog-ai-task', route }],
        ])
        capture.mockRestore()
        expect({
            seeded: seed?.prompt ?? null,
            sidePanelTab: sidePanelStateLogic.values.sidePanelOpen ? sidePanelStateLogic.values.selectedTab : null,
            newTab: (newInternalTab as jest.Mock).mock.calls.map(([url]) => url),
            path: removeProjectIdIfPresent(router.values.location.pathname) + router.values.location.search,
        }).toEqual({
            seeded: route === 'side-panel-task' ? 'Find the missing session ID' : null,
            sidePanelTab: route === 'side-panel-task' ? SidePanelTab.Max : null,
            newTab: route === 'legacy-ask' ? [urls.ai(undefined, 'Find the missing session ID')] : [],
            path: route === 'ai-scene' ? urls.ai(undefined, 'Find the missing session ID') : '/logs',
        })
    })
})
