import { dayjs } from 'lib/dayjs'

import type { ReleaseDTOApi } from './generated/api.schemas'
import { RelatedSurvey } from './releaseRelated'
import { RolloutStep } from './releaseRollout'
import { Scale, buildTrack, mergeOverlapping, rolloutSegments, surveyStatus } from './releaseTracks'
import { ReleaseSpan, buildReleaseIndex, buildReleaseRow } from './releaseUtils'

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

describe('rolloutSegments', () => {
    const scale: Scale = { start: dayjs('2026-11-01T00:00:00Z'), days: 30, day: 10 }
    const today = dayjs('2026-11-11T12:00:00Z')
    const step = (from: string, to: string, percent: number, upcoming = false): RolloutStep =>
        ({ from, to, percent, label: `${percent}%`, upcoming }) as RolloutStep

    it('drops steps that ended before the window, ends the current step today and projects to the next one', () => {
        const segments = rolloutSegments(
            [
                step('2026-09-01T00:00:00Z', '2026-09-20T00:00:00Z', 5),
                step('2026-09-20T00:00:00Z', '2026-11-05T00:00:00Z', 20),
                step('2026-11-05T00:00:00Z', '2026-11-11T12:00:00Z', 50),
                step('2026-11-15T00:00:00Z', '2026-12-01T00:00:00Z', 100, true),
            ],
            scale,
            today
        )

        expect(segments.map(({ step, left, width, projected }) => [step.percent, left, width, projected])).toEqual([
            [20, 0, 40, false],
            [50, 40, 65, false],
            [50, 105, 35, true],
            [100, 140, 108, false],
        ])
    })

    it('keeps a step that runs into the window from before it', () => {
        const segments = rolloutSegments([step('2026-09-01T00:00:00Z', '2026-11-11T12:00:00Z', 50)], scale, today)

        expect(segments.map(({ left, width }) => [left, width])).toEqual([[0, 105]])
    })
})
