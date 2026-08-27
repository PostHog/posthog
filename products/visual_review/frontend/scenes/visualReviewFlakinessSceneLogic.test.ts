import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { FlakinessOverviewApi } from '../generated/api.schemas'
import { visualReviewFlakinessSceneLogic } from './visualReviewFlakinessSceneLogic'

const REPO_ID = '00000000-0000-0000-0000-0000000000bb'
const FLAKINESS_URL = `/api/projects/:team_id/visual_review/repos/${REPO_ID}/flakiness/`

const overview: FlakinessOverviewApi = {
    entries: [],
    totals: {
        listed: 0,
        tracked: 4494,
        broken: 18,
        unstable: 231,
        at_risk: 63,
        noisy: 604,
        clean: 812,
        quarantined: 47,
        needs_decision: 12,
        by_run_type: {},
    },
    truncated: false,
    generated_at: '2026-06-10T10:00:00Z',
}

describe('visualReviewFlakinessSceneLogic', () => {
    let logic: ReturnType<typeof visualReviewFlakinessSceneLogic.build>
    let overviewRequests = 0

    afterEach(() => {
        logic?.unmount()
    })

    describe('when the overview loads', () => {
        beforeEach(() => {
            initKeaTests()
            useMocks({ get: { [FLAKINESS_URL]: overview } })
            logic = visualReviewFlakinessSceneLogic({ repoId: REPO_ID })
            logic.mount()
        })

        it('reports no error', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.loadError).toBeNull()
            expect(logic.values.overview).toEqual(overview)
        })

        // Server totals, not counts over the returned entries, so the tiles stay
        // right when the payload is capped.
        it('takes the stat counts from server totals rather than the listed entries', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.statCounts).toEqual({
                needs_decision: 12,
                broken: 18,
                unstable: 231,
                at_risk: 63,
                quiet: 1416,
                quarantined: 47,
            })
        })
    })

    describe('when the default preset has nothing in it', () => {
        // A fixed default lands on an empty table whenever this repo has nothing
        // in that bucket, and every candidate is empty on some repo. The page has
        // to move to the most urgent preset that has rows.
        // Totals say twelve need a decision while none of the listed entries
        // does, which is what a capped response looks like. Landing on the
        // totals would put a filled tile over an empty table.
        const nothingNeedsADecision: FlakinessOverviewApi = {
            ...overview,
            entries: [
                {
                    identifier: 'components-chart--donut--dark',
                    run_type: 'storybook',
                    browser: null,
                    thumbnail_hash: null,
                    width: null,
                    height: null,
                    variant_count: 0,
                    hard_count: 40,
                    soft_count: 0,
                    window_runs: 41,
                    hard_rate: 40 / 41,
                    soft_rate: 0,
                    last_flaked_at: '2026-06-10T09:00:00Z',
                    avg_diff_percentage: null,
                    worst_soft_diff_percentage: null,
                    headroom: null,
                    baseline_age_days: 3,
                    daily_hard_counts: [],
                    daily_soft_counts: [],
                    baseline_moved_day_index: null,
                    flakiness_state: 'broken',
                    is_quarantined: false,
                    needs_decision: false,
                    quarantine: null,
                },
            ],
        }

        beforeEach(() => {
            initKeaTests()
            useMocks({ get: { [FLAKINESS_URL]: nothingNeedsADecision } })
            logic = visualReviewFlakinessSceneLogic({ repoId: REPO_ID })
            logic.mount()
        })

        it('lands on the most urgent preset that has rows', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.filters.preset).toBe('broken')
        })

        it('keeps the landed preset when the filters are cleared', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setSearch('button')
            logic.actions.clearAllFilters()
            expect(logic.values.filters.search).toBe('')
            expect(logic.values.filters.preset).toBe('broken')
        })

        it('leaves a preset the link asked for alone', async () => {
            router.actions.push(`/visual_review/repos/${REPO_ID}/flakiness`, {}, { preset: 'at_risk' })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.filters.preset).toBe('at_risk')
        })

        it('leaves the default preset alone when the link names it', async () => {
            router.actions.push(`/visual_review/repos/${REPO_ID}/flakiness`, {}, { preset: 'needs_decision' })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.filters.preset).toBe('needs_decision')
        })
    })

    describe('when the preset arrives in the URL', () => {
        beforeEach(() => {
            initKeaTests()
            useMocks({ get: { [FLAKINESS_URL]: overview } })
            logic = visualReviewFlakinessSceneLogic({ repoId: REPO_ID })
            logic.mount()
        })

        // `settled` was this page's name for these rows before it scored on
        // failure rate. A link carrying it has to land on the rows it asked
        // for, and an unrecognized value has to land somewhere workable rather
        // than filter every row away.
        it.each([
            ['quiet', 'quiet'],
            ['settled', 'quiet'],
            ['noisy', 'quiet'],
            ['broken', 'broken'],
            ['nonsense', 'needs_decision'],
        ])('resolves %s to the %s preset', async (hashValue, expected) => {
            router.actions.push(`/visual_review/repos/${REPO_ID}/flakiness`, {}, { preset: hashValue })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.filters.preset).toBe(expected)
        })
    })

    describe('while quarantine writes are in flight', () => {
        beforeEach(() => {
            initKeaTests()
            overviewRequests = 0
            useMocks({
                get: {
                    [FLAKINESS_URL]: () => {
                        overviewRequests += 1
                        return overview
                    },
                },
                post: { '/api/projects/:team_id/visual_review/repos/:id/quarantine/:runType/': { ok: true } },
            })
            logic = visualReviewFlakinessSceneLogic({ repoId: REPO_ID })
            logic.mount()
        })

        // The sibling checkbox submits the light and dark identifiers together,
        // so one row can have two writes running. Tracking a single key let the
        // first response re-enable a row whose own write was still going.
        it('keeps a row pending until every one of its writes settles', async () => {
            logic.actions.quarantineIdentifier('story--dark', 'storybook', 'flaky', null, null)
            logic.actions.quarantineIdentifier('story--dark', 'storybook', 'flaky', null, null)
            expect(logic.values.pendingQuarantineKeys).toEqual(['storybook::story--dark', 'storybook::story--dark'])

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.pendingQuarantineKeys).toEqual([])
        })

        // Each write used to reload on its own success, so the earlier reload
        // could read before the sibling committed and land last, replacing the
        // fresh response with a half-applied one.
        it('reloads once, after the last write settles', async () => {
            overviewRequests = 0
            await expectLogic(logic, () => {
                logic.actions.quarantineIdentifier('story--dark', 'storybook', 'flaky', null, null)
                logic.actions.quarantineIdentifier('story--light', 'storybook', 'flaky', null, null)
            }).toFinishAllListeners()

            expect(logic.values.pendingQuarantineKeys).toEqual([])
            expect(overviewRequests).toBe(1)
        })
    })

    describe('when the overview fails to load', () => {
        beforeEach(() => {
            initKeaTests()
            useMocks({ get: { [FLAKINESS_URL]: () => [500, { detail: 'Upstream timed out' }] } })
            logic = visualReviewFlakinessSceneLogic({ repoId: REPO_ID })
            logic.mount()
        })

        // A failed load leaves `overview` null, which is what an empty repo also
        // looks like. Without `loadError` the scene renders "every snapshot
        // renders the same way every time" over a request that never answered.
        it('records the error so the scene can tell it from an empty repo', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.loadError).not.toBeNull()
            expect(logic.values.overview).toBeNull()
        })
    })
})
