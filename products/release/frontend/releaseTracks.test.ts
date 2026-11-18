import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { ReleaseDTOApi } from './generated/api.schemas'
import { RelatedSurvey } from './releaseRelated'
import { RolloutStep } from './releaseRollout'
import {
    Scale,
    buildTrack,
    mergeOverlapping,
    rolloutSegments,
    spanWidth,
    surveyStatus,
    todayScrollLeft,
} from './releaseTracks'
import { ReleaseEvent, ReleaseRow, ReleaseSpan, buildReleaseIndex, buildReleaseRow } from './releaseUtils'

const span = (key: string, kind: ReleaseSpan['kind'], from: string, to: string, label: string): ReleaseSpan => ({
    key,
    kind,
    from,
    to,
    label,
    href: `/${key}`,
})

describe('mergeOverlapping', () => {
    it('merges overlapping experiments but keeps early access on its own', () => {
        const merged = mergeOverlapping([
            span('ea', 'early_access', '2026-11-01', '2026-11-12', 'Early access, beta'),
            span('exp-1', 'experiment', '2026-11-03', '2026-11-12', 'Experiment, day 9'),
            span('exp-2', 'experiment', '2026-11-05', '2026-11-12', 'Experiment, day 7'),
        ])
        expect(merged.map(({ href, label }) => [href, label])).toEqual([
            ['/ea', 'Early access, beta'],
            ['/exp-1', '2 experiments'],
        ])
    })
})

describe('spanWidth', () => {
    const scale: Scale = { start: dayjs('2026-11-01T00:00:00Z'), days: 30, day: 10 }

    it('extends an undated span to the visible edge and keeps a dated span bounded', () => {
        const undated = { ...span('open', 'experiment', '2026-11-05', '2026-11-11', 'Running'), ongoing: true }
        const dated = span('closed', 'experiment_done', '2026-11-05', '2026-11-11', 'Complete')

        expect(spanWidth(undated, scale)).toBe(260)
        expect(spanWidth(dated, scale)).toBe(65)
    })
})

const SURVEY: RelatedSurvey = {
    id: 'survey-1',
    name: 'Feedback',
    createdAt: '2026-11-01T00:00:00Z',
    startDate: null,
    endDate: null,
    linkedFlagId: null,
    archived: false,
}

describe('survey lanes', () => {
    it.each([
        ['a draft', {}, 'Draft'],
        ['a running survey', { startDate: '2026-11-02T00:00:00Z' }, 'Running'],
        ['a finished survey', { startDate: '2026-11-02T00:00:00Z', endDate: '2026-11-05T00:00:00Z' }, 'Complete'],
        ['an archived survey that never ended', { startDate: '2026-11-02T00:00:00Z', archived: true }, 'Archived'],
    ])('reads %s as %s', (_name, extra, status) => {
        expect(surveyStatus({ ...SURVEY, ...extra })).toBe(status)
    })

    it('ends an archived survey at its start instead of today and does not mark it live', () => {
        const release = {
            id: 'release-1',
            name: 'Quiet theme',
            description: '',
            owner: null,
            feature_flag_ids: [],
            has_hidden_flags: false,
            broadcast_ids: [],
            survey_ids: [SURVEY.id],
            surveys: [],
            insight_ids: [],
            metric_insight_ids: [],
            metric_goals: [],
            insights: [],
            broadcasts: [],
            created_at: '2026-10-02T00:00:00Z',
        } as unknown as ReleaseDTOApi
        const row = buildReleaseRow(
            release,
            buildReleaseIndex([], [], [], [], { complete: true, resolvedFlagIds: [], unknownFlagIds: [] })
        )
        const archived = { ...SURVEY, startDate: '2026-11-02T00:00:00Z', archived: true }

        const lane = buildTrack(row, new Map(), { surveys: [archived], insights: [] }).lanes.find(
            (item) => item.kind === 'survey'
        )

        expect(lane && 'span' in lane ? [lane.live, lane.span?.to, lane.span?.label] : null).toEqual([
            false,
            '2026-11-02T00:00:00Z',
            'Survey archived',
        ])
    })
})

describe('flag and broadcast lanes', () => {
    it('gives each lane only its own upcoming schedules and sends', () => {
        const event = (key: string, extra: Partial<ReleaseEvent>): ReleaseEvent => ({
            key,
            date: '2026-11-10T00:00:00Z',
            kind: 'schedule',
            title: key,
            ...extra,
        })
        const row = {
            flags: [
                { id: 1, key: 'flag-one', created_at: '2026-11-01T00:00:00Z' },
                { id: 2, key: 'flag-two', created_at: '2026-11-01T00:00:00Z' },
            ],
            experiments: [],
            earlyAccess: [],
            broadcasts: [
                { id: 'b-1', name: 'One', status: 'active' },
                { id: 'b-2', name: 'Two', status: 'draft' },
            ],
            audiences: [],
            spans: [],
            events: [
                event('one-next', { upcoming: true, flagId: 1 }),
                event('one-past', { upcoming: false, flagId: 1 }),
                event('two-next', { upcoming: true, flagId: 2 }),
                event('one-later', { upcoming: true, flagId: 1 }),
                event('send-one', { kind: 'broadcast', href: urls.broadcast('b-1') }),
                event('send-two', { kind: 'broadcast', href: urls.broadcast('b-2') }),
                event('flag-change', { kind: 'flag', flagId: 1, href: urls.broadcast('b-1') }),
            ],
        } as unknown as ReleaseRow

        const lanes = buildTrack(row, new Map()).lanes

        expect(lanes.map((lane) => [lane.key, 'events' in lane ? lane.events.map(({ key }) => key) : null])).toEqual([
            ['flag-1', ['one-next', 'one-later']],
            ['flag-2', ['two-next']],
            ['broadcast-b-1', ['send-one']],
            ['broadcast-b-2', ['send-two']],
        ])
    })
})

describe('rolloutSegments', () => {
    const scale: Scale = { start: dayjs('2026-11-01T00:00:00Z'), days: 30, day: 10 }
    const today = dayjs('2026-11-11T12:00:00Z')
    const step = (from: string, to: string, percent: number, upcoming = false): RolloutStep =>
        ({ from, to, percent, label: `${percent}%`, upcoming }) as RolloutStep

    it('drops steps outside the window, ends the current step today and projects to the next one', () => {
        const segments = rolloutSegments(
            [
                step('2026-09-01T00:00:00Z', '2026-09-20T00:00:00Z', 5),
                step('2026-09-20T00:00:00Z', '2026-11-05T00:00:00Z', 20),
                step('2026-11-05T00:00:00Z', '2026-11-11T12:00:00Z', 50),
                step('2026-11-15T00:00:00Z', '2026-12-01T00:00:00Z', 100, true),
                step('2026-12-03T00:00:00Z', '2026-12-20T00:00:00Z', 100, true),
            ],
            scale,
            today
        )

        expect(segments.map(({ step, left, width, projected }) => [step.percent, left, width, projected])).toEqual([
            [20, 0, 40, false],
            [50, 40, 65, false],
            [50, 105, 35, true],
            [100, 140, 160, false],
        ])
    })

    it.each([
        ['active', false, 300],
        ['archived', true, 105],
    ])('bounds the final step for a %s flag without schedules', (_status, isArchived, width) => {
        const segments = rolloutSegments(
            [step('2026-09-01T00:00:00Z', '2026-11-11T12:00:00Z', 50)],
            scale,
            today,
            isArchived
        )

        expect(segments.map(({ left, width: segmentWidth }) => [left, segmentWidth])).toEqual([[0, width]])
    })

    it('extends the final scheduled step to the visible edge', () => {
        const segments = rolloutSegments(
            [
                step('2026-11-05T00:00:00Z', '2026-11-11T12:00:00Z', 50),
                step('2026-11-15T00:00:00Z', '2026-11-30T00:00:00Z', 100, true),
            ],
            scale,
            today
        )

        expect(segments.map(({ left, width, projected }) => [left, width, projected])).toEqual([
            [40, 65, false],
            [105, 35, true],
            [140, 160, false],
        ])
    })
})

describe('todayScrollLeft', () => {
    const scale: Scale = { start: dayjs('2026-11-01T00:00:00Z'), days: 30, day: 10 }
    const today = dayjs('2026-11-11T12:00:00Z')

    it.each([
        ['leaves the calendar alone while today sits in the left part of the view', today, 400, 100, null],
        ['moves today off the right edge even when it is visible', today, 220, 100, 27],
        ['scrolls today into view past the sticky column', today, 200, 100, 40],
    ])('%s', (_name, day, viewportWidth, stickyWidth, expected) => {
        expect(todayScrollLeft(scale, viewportWidth, stickyWidth, day)).toBe(expected)
    })
})
