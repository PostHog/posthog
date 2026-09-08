import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
// Imported from the source module rather than the `@posthog/lemon-ui` barrel, so the spies below
// replace the methods on the same `lemonToast` singleton the logic calls at runtime.
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutConfigList,
    signalsScoutConfigSync,
    signalsScoutConfigUpdate,
    signalsScoutRunsRecentPerScout,
    signalsScoutRunsTokenCosts,
    signalsScoutSuggestionsDismiss,
    signalsScoutSuggestionsList,
    signalsScoutSuggestionsRefresh,
} from 'products/signals/frontend/generated/api'
import type {
    ScoutSuggestionItemApi,
    ScoutSuggestionSetApi,
    SignalScoutConfigApi,
} from 'products/signals/frontend/generated/api.schemas'
import { llmSkillsNameRetrieve } from 'products/skills/frontend/generated/api'

import { INBOX_EVENTS } from '../inboxAnalytics'
import { scoutFleetLogic } from './scoutFleetLogic'
import { scoutSuggestionsLogic } from './scoutSuggestionsLogic'

jest.mock('posthog-js')
jest.mock('products/skills/frontend/generated/api', () => ({
    llmSkillsNameArchiveCreate: jest.fn(),
    llmSkillsNameRetrieve: jest.fn(),
}))
jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutChatTasksCreate: jest.fn(),
    signalsScoutConfigDestroy: jest.fn(),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigSync: jest.fn(),
    signalsScoutConfigUpdate: jest.fn(),
    signalsScoutMetadataGet: jest.fn(),
    signalsScoutRunsFindingsSummary: jest.fn(),
    signalsScoutRunsList: jest.fn(),
    signalsScoutRunsRecentPerScout: jest.fn(),
    signalsScoutRunsTokenCosts: jest.fn(),
    signalsScoutSuggestionsDismiss: jest.fn(),
    signalsScoutSuggestionsList: jest.fn(),
    signalsScoutSuggestionsRefresh: jest.fn(),
}))

const mockList = signalsScoutSuggestionsList as jest.MockedFunction<typeof signalsScoutSuggestionsList>
const mockDismiss = signalsScoutSuggestionsDismiss as jest.MockedFunction<typeof signalsScoutSuggestionsDismiss>
const mockRefresh = signalsScoutSuggestionsRefresh as jest.MockedFunction<typeof signalsScoutSuggestionsRefresh>
const mockConfigList = signalsScoutConfigList as jest.MockedFunction<typeof signalsScoutConfigList>
const mockConfigSync = signalsScoutConfigSync as jest.MockedFunction<typeof signalsScoutConfigSync>
const mockConfigUpdate = signalsScoutConfigUpdate as jest.MockedFunction<typeof signalsScoutConfigUpdate>
const mockRunsRecentPerScout = signalsScoutRunsRecentPerScout as jest.MockedFunction<
    typeof signalsScoutRunsRecentPerScout
>
const mockRunsTokenCosts = signalsScoutRunsTokenCosts as jest.MockedFunction<typeof signalsScoutRunsTokenCosts>
const mockSkillRetrieve = llmSkillsNameRetrieve as jest.MockedFunction<typeof llmSkillsNameRetrieve>

const CANONICAL_ITEM: ScoutSuggestionItemApi = {
    id: 'suggestion-1',
    kind: 'canonical',
    skill_name: 'signals-scout-web-vitals',
    title: 'Watch web vitals on the checkout page',
    why_here: 'Checkout has the slowest LCP of any page in this project.',
    description: '',
    draft_body: '',
    proposed_config: { run_cron_schedule: null, run_interval_minutes: 1440, emit: true },
    gap: true,
    confidence: 'high',
}

const CUSTOM_ITEM: ScoutSuggestionItemApi = {
    ...CANONICAL_ITEM,
    id: 'suggestion-2',
    kind: 'custom',
    skill_name: 'signals-scout-signup-drop-off',
    title: 'Watch signup drop-off',
    description: 'Investigates sudden drops in completed signups.',
    draft_body: 'Check the signup funnel every day.',
    gap: false,
    confidence: 'medium',
}

const CONFIG: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: CANONICAL_ITEM.skill_name,
    description: 'Watches web vitals.',
    scout_origin: 'canonical',
    owners: [],
    enabled: false,
    status: 'active',
    pause_reason: null,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: null,
    output_destinations: {},
    structured_output_schema: null,
    mcp_gateway_server_ids: [],
    write_scopes: [],
    last_run_at: null,
    consecutive_failure_count: 0,
    status_changed_at: null,
    auto_pause_exempt: false,
    network_access: 'trusted',
    model: null,
    source_product: null,
    source_id: null,
    created_at: '2026-07-22T00:00:00Z',
}

function suggestionSet(overrides: Partial<ScoutSuggestionSetApi> = {}): ScoutSuggestionSetApi {
    return {
        status: 'fresh',
        generated_at: '2026-09-01T00:00:00Z',
        model: '',
        fleet_snapshot: [],
        items: [CANONICAL_ITEM, CUSTOM_ITEM],
        ...overrides,
    }
}

describe('scoutSuggestionsLogic', () => {
    let logic: ReturnType<typeof scoutSuggestionsLogic.build>

    function setSuggestionsFlag(enabled: boolean): void {
        featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.SCOUTS_SUGGESTIONS_UI] : [], {
            [FEATURE_FLAGS.SCOUTS_SUGGESTIONS_UI]: enabled,
        })
    }

    beforeEach(() => {
        // The strip's collapsed and closed state persists per user and project, so one test's
        // chevron would otherwise decide how the next one opens.
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
        setSuggestionsFlag(true)
        mockList.mockReset().mockResolvedValue(suggestionSet())
        mockDismiss.mockReset().mockResolvedValue(CANONICAL_ITEM)
        mockRefresh.mockReset().mockResolvedValue({ workflow_id: 'workflow-1' })
        mockConfigList.mockReset().mockResolvedValue([CONFIG])
        mockConfigSync.mockReset().mockResolvedValue([CONFIG])
        mockConfigUpdate.mockReset().mockResolvedValue({ ...CONFIG, enabled: true })
        mockRunsRecentPerScout.mockReset().mockResolvedValue([])
        mockRunsTokenCosts.mockReset().mockResolvedValue({ costs: [], available: true })
        mockSkillRetrieve.mockReset().mockResolvedValue({
            name: CANONICAL_ITEM.skill_name,
            description: 'Watches web vitals.',
            body: '# Web vitals\n\nCheck LCP on every run.',
        } as Awaited<ReturnType<typeof llmSkillsNameRetrieve>>)
    })

    afterEach(() => {
        logic?.unmount()
    })

    async function mountWithBatch(set: ScoutSuggestionSetApi = suggestionSet()): Promise<void> {
        mockList.mockResolvedValue(set)
        logic = scoutSuggestionsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        scoutFleetLogic.actions.loadScoutConfigsSuccess([CONFIG])
    }

    it('reads nothing until the person is on the suggestions flag', async () => {
        setSuggestionsFlag(false)
        await mountWithBatch()

        expect(mockList).not.toHaveBeenCalled()
        expect(logic.values.hasPicks).toBe(false)

        // Flags usually resolve after the tab mounts, so the answer arriving is what starts the read.
        setSuggestionsFlag(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockList).toHaveBeenCalledTimes(1)
        expect(logic.values.hasPicks).toBe(true)
    })

    // Whatever the batch row says, a batch with no picks has nothing to put on the roster.
    it.each([
        ['never scanned', 'empty', null],
        ['scanned and found nothing', 'empty', '2026-09-01T00:00:00Z'],
        ['last scan failed', 'failed', null],
    ])('keeps the strip off a batch with no picks: %s', async (_name, status, generatedAt) => {
        await mountWithBatch(
            suggestionSet({ status: status as ScoutSuggestionSetApi['status'], generated_at: generatedAt, items: [] })
        )

        expect(logic.values.hasPicks).toBe(false)
        expect(logic.values.stripVisible).toBe(false)
    })

    // The header button is the entry point whenever the strip is off screen, so it has to cover
    // both reasons it can be: closed by the person, and empty because the project has no picks.
    it.each([
        ['pays for a scan when there is nothing to reopen', [] as ScoutSuggestionItemApi[], 1],
        ['only reopens the strip when picks are waiting', [CANONICAL_ITEM, CUSTOM_ITEM], 0],
    ])('the header button %s', async (_name, items, refreshCalls) => {
        await mountWithBatch(suggestionSet({ items }))
        logic.actions.hideStrip()
        expect(logic.values.stripVisible).toBe(false)

        logic.actions.askForSuggestions()
        await expectLogic(logic).toFinishAllListeners()

        // Either way the strip is back on screen: with the picks, or with the scan's skeletons.
        expect(logic.values.stripVisible).toBe(true)
        expect(mockRefresh).toHaveBeenCalledTimes(refreshCalls)
    })

    it('re-reads the batch instead of paying for a scan when the read never landed', async () => {
        mockList.mockRejectedValue(new ApiError('nope', 500))
        logic = scoutSuggestionsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.suggestionSet).toBeNull()

        logic.actions.askForSuggestions()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockRefresh).not.toHaveBeenCalled()
        expect(mockList).toHaveBeenCalledTimes(2)
    })

    // The strip closes on an empty batch, so this toast is the whole report on the scan. A scan
    // that never finished is worth another press; one that ran and found nothing is not.
    it.each([
        ['found nothing', { status: 'empty', generated_at: '2026-09-03T00:00:00Z' }, 'info'],
        ['did not finish', { status: 'failed' }, 'error'],
    ])('reports how a scan that left no picks ended: %s', async (_name, outcome, level) => {
        const toast = jest.spyOn(lemonToast, level as 'info' | 'error').mockReturnValue('toast-1')
        await mountWithBatch()

        logic.actions.requestRefresh()
        await expectLogic(logic).toFinishAllListeners()
        mockList.mockResolvedValue(suggestionSet({ ...(outcome as Partial<ScoutSuggestionSetApi>), items: [] }))
        logic.actions.loadSuggestions()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isRefreshing).toBe(false)
        expect(logic.values.stripVisible).toBe(false)
        expect(toast).toHaveBeenCalledTimes(1)
        toast.mockRestore()
    })

    it('keeps a stale batch visible, because its picks are still valid', async () => {
        await mountWithBatch(suggestionSet({ status: 'stale' }))

        expect(logic.values.hasPicks).toBe(true)
        expect(logic.values.suggestions).toHaveLength(2)
    })

    it('hides a dismissed suggestion before the request lands', async () => {
        await mountWithBatch()

        logic.actions.dismissSuggestion(CANONICAL_ITEM, 'strip')

        expect(logic.values.suggestions.map((item) => item.id)).toEqual([CUSTOM_ITEM.id])
        await expectLogic(logic).toFinishAllListeners()
        expect(mockDismiss).toHaveBeenCalledWith(String(MOCK_TEAM_ID), CANONICAL_ITEM.id)
    })

    it('brings a suggestion back when the dismiss fails, since there is nothing to undo', async () => {
        await mountWithBatch()
        mockDismiss.mockRejectedValueOnce(new ApiError('nope', 500))

        logic.actions.dismissSuggestion(CANONICAL_ITEM, 'strip')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.suggestions.map((item) => item.id)).toEqual([CANONICAL_ITEM.id, CUSTOM_ITEM.id])
    })

    it('opens a canonical pick on the scout that exists, and only drops it once it is on', async () => {
        await mountWithBatch()

        logic.actions.openCreateFromSuggestion(CANONICAL_ITEM, 'strip')
        await expectLogic(logic).toFinishAllListeners()

        // The form shows the existing scout's own text, not the pick's, and knows which config to turn on.
        expect(mockSkillRetrieve).toHaveBeenCalledWith(String(MOCK_TEAM_ID), CANONICAL_ITEM.skill_name)
        expect(logic.values.createFromSuggestion).toEqual({
            item: CANONICAL_ITEM,
            existing: {
                config: CONFIG,
                description: 'Watches web vitals.',
                body: '# Web vitals\n\nCheck LCP on every run.',
            },
        })
        expect(logic.values.busySuggestionIds).toEqual([])

        // A draft needs no read, so its form opens at once.
        logic.actions.openCreateFromSuggestion(CUSTOM_ITEM, 'strip')
        expect(logic.values.createFromSuggestion).toEqual({ item: CUSTOM_ITEM, existing: null })

        // The roster rolls a failed write back, and the offer has to come back with it.
        scoutFleetLogic.actions.loadScoutConfigsSuccess([CONFIG])
        expect(logic.values.suggestions.map((item) => item.id)).toContain(CANONICAL_ITEM.id)

        scoutFleetLogic.actions.loadScoutConfigsSuccess([{ ...CONFIG, enabled: true }])
        expect(logic.values.suggestions.map((item) => item.id)).toEqual([CUSTOM_ITEM.id])
    })

    it('reports a card-body press as the button it stands in for, marked as the card', async () => {
        await mountWithBatch()
        ;(posthog.capture as jest.Mock).mockClear()

        logic.actions.openCreateFromSuggestion(CUSTOM_ITEM, 'strip', 'card')
        logic.actions.openCreateFromSuggestion(CUSTOM_ITEM, 'strip')
        await expectLogic(logic).toFinishAllListeners()

        const clicks = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === INBOX_EVENTS.SCOUT_SUGGESTION_CLICKED
        )
        expect(clicks.map(([, properties]) => [properties.click_target, properties.via])).toEqual([
            ['create', 'card'],
            ['create', 'button'],
        ])
    })

    it('sends one refresh request however often the button is pressed while it is out', async () => {
        await mountWithBatch()

        logic.actions.requestRefresh()
        logic.actions.requestRefresh()
        expect(logic.values.isRefreshing).toBe(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockRefresh).toHaveBeenCalledTimes(1)
        expect(logic.values.isRefreshing).toBe(true)
    })

    it('waits for the scan when a refresh is already running', async () => {
        await mountWithBatch()
        mockRefresh.mockRejectedValueOnce(new ApiError('A refresh is already running for this project.', 409))

        logic.actions.requestRefresh()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isRefreshing).toBe(true)
    })

    it('does not wait for a scan the daily cap refused', async () => {
        await mountWithBatch()
        mockRefresh.mockRejectedValueOnce(new ApiError("You've reached today's limit.", 429))

        logic.actions.requestRefresh()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isRefreshing).toBe(false)
    })

    it('keeps waiting when the row was already failed before the refresh', async () => {
        await mountWithBatch(suggestionSet({ status: 'failed' }))

        logic.actions.requestRefresh()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadSuggestions()
        await expectLogic(logic).toFinishAllListeners()

        // The unchanged old failure is not the new scan settling.
        expect(logic.values.isRefreshing).toBe(true)
    })

    it('stops waiting once the scan produces a newer batch', async () => {
        await mountWithBatch()

        logic.actions.requestRefresh()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.isRefreshing).toBe(true)

        mockList.mockResolvedValue(suggestionSet({ generated_at: '2026-09-03T00:00:00Z' }))
        logic.actions.loadSuggestions()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isRefreshing).toBe(false)
    })

    it('opens collapsed, closes with the cross, and comes back open', async () => {
        await mountWithBatch()
        expect(logic.values.collapsed).toBe(true)
        expect(logic.values.stripHidden).toBe(false)

        logic.actions.setCollapsed(false)
        expect(logic.values.collapsed).toBe(false)

        logic.actions.setCollapsed(true)
        logic.actions.hideStrip()
        expect(logic.values.stripHidden).toBe(true)

        // Asking for the picks back means reading them, so the strip returns open.
        logic.actions.showStrip()
        expect(logic.values.stripHidden).toBe(false)
        expect(logic.values.collapsed).toBe(false)
    })
})
