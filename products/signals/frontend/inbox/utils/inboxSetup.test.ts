import { mockScoutConfigs, mockScoutSuggestionSet } from '../__mocks__/scoutConfigs'
import type { AgentRosterSource } from '../components/config/agentRosterMeta'
import type { SourceProductStatus } from '../signalSourcesLogic'
import { newInboxSetupDraft, reconcileInboxSetupDraft, setupSources } from './inboxSetup'
import { inboxSetupDefaultScouts, inboxSetupScoutChoices } from './inboxSetupScouts'

describe('Inbox setup defaults', () => {
    it.each(['none', 'loading', 'error'] as const)(
        'does not enable error tracking when its data is %s',
        (dataStatus) => {
            const sources = setupSources(
                [],
                {
                    error_tracking: {
                        enabled: true,
                        productName: 'Error tracking',
                        enablement: 'error_tracking',
                        dataStatus,
                    },
                },
                0,
                {},
                false
            )
            expect(newInboxSetupDraft(sources, []).sources).toEqual([])
        }
    )

    it('selects available signals without enabling automatic implementation', () => {
        const sources = setupSources(
            [],
            {
                error_tracking: {
                    enabled: true,
                    productName: 'Error tracking',
                    enablement: 'error_tracking',
                    dataStatus: 'recent',
                },
            },
            1,
            {},
            false
        )
        const draft = newInboxSetupDraft(sources, ['scanner-id'])
        expect(draft.sources).toHaveLength(3)
        expect(draft.sources.every((source) => source.enabled)).toBe(true)
        expect(draft.scanner_ids).toEqual(['scanner-id'])
        expect(draft.automatic_implementation).toBe(false)
        expect(draft.implementation_priority).toBe('P1')
    })

    it('uses connected warehouse sources before a signal config exists, without confusing GitHub code access with issue sync', () => {
        const sources = setupSources([], {}, 0, {}, false, [
            { id: 'linear-source', source_type: 'Linear', schemas: [{ name: 'issues' }] },
        ])
        expect(newInboxSetupDraft(sources, []).sources).toEqual([
            { source_product: 'linear', source_type: 'issue', enabled: true },
        ])
        expect(sources.find((source) => source.definition.source === 'github')?.available).toBe(false)
        expect(sources.some((source) => source.definition.source === 'pganalyze')).toBe(false)
        const missingTables = setupSources([], {}, 0, {}, false, [
            { id: 'github-source', source_type: 'Github', schemas: [] },
        ])
        const github = missingTables.find((source) => source.definition.source === 'github')
        expect(github?.available).toBe(false)
        expect(github?.setupUrl).toContain('github-source')
        expect(newInboxSetupDraft(missingTables, []).sources).toEqual([])
    })

    it.each([
        { available: null, expected: ['retained', 'removed'] },
        { available: ['retained', 'new'], expected: ['retained'] },
        { available: [], expected: [] },
    ])('reconciles selected scanners only after loading: $available', ({ available, expected }) => {
        const draft = newInboxSetupDraft([], ['retained', 'removed'])
        expect(reconcileInboxSetupDraft(draft, [], available).scanner_ids).toEqual(expected)
        expect(reconcileInboxSetupDraft({ ...draft, scanner_ids: [] }, [], available).scanner_ids).toEqual([])
    })

    it('keeps recommendations in place when one is selected', () => {
        const items = mockScoutSuggestionSet().items
        expect(inboxSetupScoutChoices(items, [items[1]])).toEqual(items)
        expect(inboxSetupScoutChoices(items, [items[1], items[0]])).toEqual(items)
        const previouslySelected = { ...items[0], id: 'previously-selected', skill_name: 'previous-scout' }
        expect(inboxSetupScoutChoices(items, [previouslySelected, items[1]])).toEqual([...items, previouslySelected])
        const canonical = { ...items[0], kind: 'canonical' as const }
        const selectedBuiltin = { ...canonical, id: 'builtin:scout-id' }
        expect(inboxSetupScoutChoices([canonical], [selectedBuiltin])).toEqual([selectedBuiltin])
    })

    it('matches built-in scouts to enabled products and connected sources', () => {
        const names = [
            'general',
            'product-analytics',
            'error-tracking',
            'session-replay',
            'replay-vision',
            'ai-observability',
            'conversations',
            'data-warehouse',
            'health-checks',
        ]
        const configs = names.map((name) => ({
            ...mockScoutConfigs[0],
            id: name,
            skill_name: `signals-scout-${name}`,
            enabled: false,
        }))
        const statuses: Partial<Record<AgentRosterSource, SourceProductStatus>> = {
            error_tracking: {
                enabled: true,
                productName: 'Error tracking',
                enablement: 'error_tracking',
                dataStatus: 'none',
            },
            replay_vision: {
                enabled: true,
                productName: 'Session replay',
                enablement: 'session_replay',
                dataStatus: 'unavailable',
            },
            llm_analytics: { enabled: true, productName: 'AI observability', enablement: null, dataStatus: 'recent' },
            conversations: {
                enabled: true,
                productName: 'Support',
                enablement: 'conversations',
                dataStatus: 'unavailable',
            },
        }
        const sources = setupSources([], statuses, 1, {}, true, [
            { id: 'linear-source', source_type: 'Linear', schemas: [{ name: 'issues' }] },
        ])
        expect(inboxSetupDefaultScouts(configs, sources, true, statuses).map((scout) => scout.skill_name)).toEqual(
            names.map((name) => `signals-scout-${name}`)
        )
        expect(inboxSetupDefaultScouts(configs, [], false).map((scout) => scout.skill_name)).toEqual([
            'signals-scout-general',
        ])
        expect(inboxSetupDefaultScouts([], sources, true)).toEqual([])
        const withoutScanners = setupSources([], statuses, 0, {}, false)
        const replayChoices = inboxSetupDefaultScouts(configs, withoutScanners, false, statuses).map(
            (scout) => scout.skill_name
        )
        expect(replayChoices).toContain('signals-scout-session-replay')
        expect(replayChoices).not.toContain('signals-scout-replay-vision')
    })

    it.each([
        { enabled: true },
        { lifecycle_locked: true },
        { scout_origin: 'custom' as const },
        { deprecation: { phase: 'announced' as const, reason: 'Retiring', superseded_by: '', sunset_at: null } },
    ])('does not recommend unavailable canonical configs: %j', (overrides) => {
        const config = {
            ...mockScoutConfigs[0],
            skill_name: 'signals-scout-product-analytics',
            enabled: false,
            ...overrides,
        }
        expect(inboxSetupDefaultScouts([config], [], true)).toEqual([])
    })
})
