import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { FEATURE_FLAG_ROLLOUT_SKILL } from 'scenes/feature-flags/featureFlagAiContext'
import { maxMocks } from 'scenes/max/testUtils'

import { MAX_SIDE_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { featureFlagRolloutPlanLogic } from './featureFlagRolloutPlanLogic'

jest.mock('posthog-js')
jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn().mockResolvedValue(true) }))

const FLAG_ID = 1
const FLAG_KEY = 'faster-report-cache'
const PROJECT_ID = 42

function setSandboxView(enabled: boolean): void {
    featureFlagLogic.actions.setFeatureFlags(
        enabled ? [FEATURE_FLAGS.PHAI_SANDBOX_MODE] : [],
        enabled ? { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true } : {}
    )
}

describe('featureFlagRolloutPlanLogic', () => {
    let logic: ReturnType<typeof featureFlagRolloutPlanLogic.build>
    const seed = (): ReturnType<typeof composerSeedLogic.build>['values']['seed'] =>
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.setSidePanelAvailable(true)
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).mount()
        logic = featureFlagRolloutPlanLogic({ id: FLAG_ID })
        logic.mount()
        ;(posthog.capture as jest.Mock).mockClear()
        ;(copyToClipboard as jest.Mock).mockClear()
    })

    afterEach(() => {
        setSandboxView(false)
        logic.unmount()
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).unmount()
    })

    it('still offers the copied prompt when the agent sandbox is unavailable', async () => {
        await expectLogic(logic).toMatchValues({ isAiPlanAvailable: false })

        await expectLogic(logic, () => {
            logic.actions.startPlan(FLAG_KEY, PROJECT_ID)
            logic.actions.copyAgentPrompt(FLAG_KEY, PROJECT_ID)
        }).toFinishAllListeners()

        expect(seed()).toBeNull()
        const prompt = (copyToClipboard as jest.Mock).mock.calls[0][0]
        expect(prompt).toContain(FEATURE_FLAG_ROLLOUT_SKILL)
        expect(prompt).toContain(FLAG_KEY)
        expect(prompt).toContain(String(PROJECT_ID))
    })

    describe('in the agent sandbox', () => {
        beforeEach(() => {
            setSandboxView(true)
        })

        it('seeds the skill and the flag identity, and opens the panel once', async () => {
            await expectLogic(logic, () => {
                logic.actions.startPlan(FLAG_KEY, PROJECT_ID)
                logic.actions.startPlan(FLAG_KEY, PROJECT_ID)
            }).toFinishAllListeners()

            const items = seed()?.contextItems ?? []
            expect(items).toContainEqual(expect.objectContaining({ type: 'skill', key: FEATURE_FLAG_ROLLOUT_SKILL }))
            const target = items.find((item) => item.type === 'feature_flag_rollout_target')
            expect(JSON.parse(target?.value ?? '')).toEqual({ project_id: PROJECT_ID, id: FLAG_ID, key: FLAG_KEY })
            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
            const clicks = (posthog.capture as jest.Mock).mock.calls.filter(
                ([event]) => event === 'feature flag rollout hint plan clicked'
            )
            expect(clicks).toHaveLength(1)
        })

        it.each([
            ['the panel closes', () => sidePanelStateLogic.actions.closeSidePanel()],
            ['the panel moves to another tab', () => sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support)],
        ])('drops the pending plan when %s, so it can start again', async (_name, leave) => {
            await expectLogic(logic, () => logic.actions.startPlan(FLAG_KEY, PROJECT_ID)).toFinishAllListeners()

            await expectLogic(logic, leave).toFinishAllListeners()

            expect(seed()).toBeNull()
            expect(logic.values.planStarted).toBe(false)

            await expectLogic(logic, () => logic.actions.startPlan(FLAG_KEY, PROJECT_ID)).toFinishAllListeners()
            expect(seed()).not.toBeNull()
        })
    })
})
