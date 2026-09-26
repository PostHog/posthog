import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    FEATURE_FLAG_CLEANUP_DISMISS_GROUP,
    FEATURE_FLAG_CLEANUP_SKILL,
    FEATURE_FLAG_CLEANUP_SKILL_CHIP_CONTEXT_ITEM,
} from 'scenes/feature-flags/featureFlagAiContext'
import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'
import { maxMocks } from 'scenes/max/testUtils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    FeatureFlagBucketingIdentifier,
    FeatureFlagEvaluationRuntime,
    FeatureFlagType,
    SidePanelTab,
} from '~/types'

import {
    attachedContextItemKey,
    attachedContextLogic,
    composerSeedLogic,
    runnerPanelLogic,
} from 'products/posthog_ai/frontend/api/logics'

import { featureFlagCleanupAssessmentLogic } from './featureFlagCleanupAssessmentLogic'

jest.mock('posthog-js')

const FLAG_ID = 1
const PROJECT_ID = 42

const FEATURE_FLAG: FeatureFlagType & { id: number } = {
    id: FLAG_ID,
    key: 'stale-flag',
    name: '',
    created_at: '2021-01-01',
    updated_at: '2021-01-01',
    created_by: null,
    is_remote_configuration: false,
    filters: { groups: [], payloads: {}, multivariate: null },
    deleted: false,
    archived: false,
    active: true,
    experiment_set: null,
    experiment_set_metadata: null,
    features: null,
    surveys: null,
    can_edit: true,
    tags: [],
    ensure_experience_continuity: null,
    user_access_level: AccessControlLevel.Admin,
    status: 'ACTIVE',
    has_encrypted_payloads: false,
    version: 0,
    last_modified_by: null,
    evaluation_runtime: FeatureFlagEvaluationRuntime.ALL,
    evaluation_contexts: [],
    bucketing_identifier: FeatureFlagBucketingIdentifier.DISTINCT_ID,
}

function setCleanupAvailable(available: boolean): void {
    featureFlagLogic.actions.setFeatureFlags(
        available ? [FEATURE_FLAGS.PHAI_SANDBOX_MODE, FEATURE_FLAGS.FEATURE_FLAG_CLEANUP_ASSESSMENT] : [],
        available
            ? { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true, [FEATURE_FLAGS.FEATURE_FLAG_CLEANUP_ASSESSMENT]: true }
            : {}
    )
}

describe('featureFlagCleanupAssessmentLogic', () => {
    let logic: ReturnType<typeof featureFlagCleanupAssessmentLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.setSidePanelAvailable(true)
        // Mounted independently (outliving `logic`) so the unmount test below proves this logic's own
        // `beforeUnmount` deregisters its entry, rather than the whole store resetting because `logic`
        // happened to be its last consumer.
        attachedContextLogic.mount()
        // The side panel holds the seed store mounted while the runner chunk loads, so a pending seed can
        // outlive this logic. Mounting it here models that.
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).mount()
        logic = featureFlagCleanupAssessmentLogic({ id: FLAG_ID })
        logic.mount()
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        logic?.unmount()
        attachedContextLogic.unmount()
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).unmount()
    })

    it('is unavailable on the legacy view even when the release flag is on', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.FEATURE_FLAG_CLEANUP_ASSESSMENT], {
            [FEATURE_FLAGS.FEATURE_FLAG_CLEANUP_ASSESSMENT]: true,
        })

        await expectLogic(logic).toMatchValues({ isCleanupAvailable: false })
    })

    it('is unavailable when the release flag is off, even on the new sandbox view', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PHAI_SANDBOX_MODE], {
            [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
        })

        await expectLogic(logic).toMatchValues({ isCleanupAvailable: false })
    })

    it('is unavailable on a self-hosted instance with no Anthropic key configured', async () => {
        preflightLogic.actions.loadPreflightSuccess({
            cloud: false,
            is_debug: false,
            anthropic_available: false,
        } as any)
        setCleanupAvailable(true)

        await expectLogic(logic).toMatchValues({ isCleanupAvailable: false })

        // `lib/logic/featureFlagLogic`'s flags survive `initKeaTests()`'s reset (posthog-js replays its
        // cached decide response on the next `posthog.init()`), so leaving them on here would leak into
        // whichever test runs next.
        setCleanupAvailable(false)
    })

    it('does nothing when started while unavailable', async () => {
        await expectLogic(logic, () => {
            logic.actions.startAssessment(FEATURE_FLAG, PROJECT_ID)
        }).toFinishAllListeners()

        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
        expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).toBeNull()
    })

    describe('when available', () => {
        beforeEach(() => {
            setCleanupAvailable(true)
        })

        it('opens the side panel on a freshly seeded, auto-submitted request', async () => {
            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG, PROJECT_ID)
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
            expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).toEqual({
                prompt: 'Assess this feature flag for cleanup.',
                autoSubmit: true,
            })
        })

        it("attaches the cleanup skill and the saved flag identity as this request's own context", async () => {
            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG, PROJECT_ID)
            }).toFinishAllListeners()

            const items = attachedContextLogic.values.contextItems
            expect(items).toContainEqual(expect.objectContaining({ type: 'skill', key: FEATURE_FLAG_CLEANUP_SKILL }))
            const target = items.find((item) => item.type === 'feature_flag_cleanup_target')
            expect(JSON.parse(target?.value ?? '')).toEqual({ project_id: PROJECT_ID, id: FLAG_ID, key: 'stale-flag' })
        })

        it('re-attaches the skill chip and its instruction even if they were dismissed in an earlier conversation', async () => {
            // A dismissal is keyed by a shared group with no expiry, so closing the chip once would
            // otherwise silently strip the assessment-only instruction from every later click.
            attachedContextLogic.actions.dismissContext(
                attachedContextItemKey(FEATURE_FLAG_CLEANUP_SKILL_CHIP_CONTEXT_ITEM),
                FEATURE_FLAG_CLEANUP_DISMISS_GROUP
            )

            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG, PROJECT_ID)
            }).toFinishAllListeners()

            const items = attachedContextLogic.values.contextItems
            expect(items).toContainEqual(expect.objectContaining({ type: 'skill', key: FEATURE_FLAG_CLEANUP_SKILL }))
            expect(items).toContainEqual(expect.objectContaining({ type: 'instructions' }))
        })

        it('does not resume whatever the panel was already showing', async () => {
            runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).actions.setActiveCreation({ streamKey: 'unrelated-run' })
            runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).actions.setHistoryExpanded(true)

            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG, PROJECT_ID)
            }).toFinishAllListeners()

            expect(runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).values.activeCreation).toBeNull()
            expect(runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).values.historyExpanded).toBe(false)
        })

        it('ignores a repeat click instead of starting a second assessment', async () => {
            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG, PROJECT_ID)
                logic.actions.startAssessment(FEATURE_FLAG, PROJECT_ID)
            }).toFinishAllListeners()

            // Filtered rather than a raw call count: opening the side panel fires its own "sidebar
            // opened" capture, so the total call count is not specific to this action.
            const clicks = (posthog.capture as jest.Mock).mock.calls.filter(
                ([event]) => event === 'feature flag stale banner review cleanup with ai clicked'
            )
            expect(clicks).toHaveLength(1)
        })

        it('detaches the request context and cancels its pending seed on unmount, so neither reaches a later conversation', async () => {
            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG, PROJECT_ID)
            }).toFinishAllListeners()
            expect(attachedContextLogic.values.contextItems).not.toHaveLength(0)

            logic.unmount()

            expect(attachedContextLogic.values.contextItems).toHaveLength(0)
            expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).toBeNull()
        })

        it.each([
            { sent: 'the cleanup target', sendsTarget: true, remaining: 0 },
            { sent: 'only unrelated context', sendsTarget: false, remaining: 3 },
        ])(
            'leaves $remaining request context items after a message carrying $sent is sent',
            async ({ sendsTarget, remaining }) => {
                await expectLogic(logic, () => {
                    logic.actions.startAssessment(FEATURE_FLAG, PROJECT_ID)
                }).toFinishAllListeners()
                const target = attachedContextLogic.values.contextItems.find(
                    (item) => item.type === 'feature_flag_cleanup_target'
                )
                const unrelatedKey = 'feature_flag:some-other-flag'

                attachedContextLogic.actions.markContextSent(
                    'task-1',
                    sendsTarget && target ? [unrelatedKey, attachedContextItemKey(target)] : [unrelatedKey]
                )

                expect(attachedContextLogic.values.contextItems).toHaveLength(remaining)
            }
        )

        it("leaves another producer's newer seed in place on unmount", async () => {
            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG, PROJECT_ID)
            }).toFinishAllListeners()
            const otherSeed = { prompt: 'Something else', autoSubmit: false }
            composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).actions.setSeed(otherSeed)

            logic.unmount()

            expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).toEqual(otherSeed)
        })
    })
})
