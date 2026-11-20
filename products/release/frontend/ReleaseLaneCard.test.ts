import { Fact, laneCardFacts } from './ReleaseLaneCard'
import { RelatedSurvey } from './releaseRelated'
import { RolloutStep } from './releaseRollout'
import { Lane, surveyStatus } from './releaseTracks'
import { ReleaseSpan } from './releaseUtils'

const SURVEY: RelatedSurvey = {
    id: 's1',
    name: 'Feedback',
    createdAt: '2026-10-30T12:00:00Z',
    startDate: '2026-11-02T12:00:00Z',
    endDate: null,
    linkedFlagId: null,
    archived: false,
}

function surveyLane(extra: Partial<RelatedSurvey>): Lane {
    const survey = { ...SURVEY, ...extra }
    return { kind: 'survey', title: survey.name, status: surveyStatus(survey), survey } as Lane
}

function flagLane(active: boolean, audience: { percent: number | null; who: string }): Lane {
    return { kind: 'flag', title: 'quiet-theme', status: active ? 'Live' : 'Off', flag: { active }, audience } as Lane
}

const experiment = (from: string): ReleaseSpan => ({
    key: 'e1',
    kind: 'experiment',
    from,
    to: '2026-11-14T12:00:00Z',
    label: 'Experiment running',
    href: '/experiments/1',
})

const step = (from: string, to: string, label: string, upcoming = false): RolloutStep =>
    ({ from, to, label, percent: 0, upcoming }) as RolloutStep

describe('laneCardFacts', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-11-14T12:00:00Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each<[string, Parameters<typeof laneCardFacts>[0], Fact[]]>([
        [
            'a survey completed today shows its end date',
            { lane: surveyLane({ endDate: '2026-11-14T09:00:00Z' }) },
            [
                ['Status', 'Complete'],
                ['Started', '2 Nov, 12 days ago'],
                ['Ended', '14 Nov, after 12 days'],
            ],
        ],
        [
            'a draft survey has not started',
            { lane: surveyLane({ startDate: null }) },
            [
                ['Status', 'Draft'],
                ['Started', 'Not yet'],
            ],
        ],
        [
            'an archived survey that never ended gets no end date',
            { lane: surveyLane({ archived: true }) },
            [
                ['Status', 'Archived'],
                ['Started', '2 Nov, 12 days ago'],
            ],
        ],
        [
            'merged experiments describe the group, not one experiment',
            {
                span: {
                    key: 'e1',
                    kind: 'experiment_done',
                    from: '2026-11-01T12:00:00Z',
                    to: '2026-11-10T12:00:00Z',
                    label: '2 experiments',
                    href: '/experiments/1',
                    count: 2,
                } as ReleaseSpan,
            },
            [
                ['Started', '1 Nov, 13 days ago'],
                ['Ended', '10 Nov, after 9 days'],
            ],
        ],
        [
            'an experiment a day short of two weeks still points to its results date',
            { span: experiment('2026-11-01T12:00:00Z') },
            [
                ['Progress', 'Day 14 of 14'],
                ['Started', '1 Nov, 13 days ago'],
                ['Results', 'Around 15 Nov'],
            ],
        ],
        [
            'an experiment with two full weeks is ready to read',
            { span: experiment('2026-10-31T12:00:00Z') },
            [
                ['Progress', 'Day 14 of 14'],
                ['Started', '31 Oct, 14 days ago'],
                ['Results', 'Ready to read'],
            ],
        ],
        [
            'a past step leaves out the current audience of a disabled flag',
            {
                lane: flagLane(false, { percent: 0, who: 'Nobody, the flag is disabled' }),
                step: step('2026-10-01T12:00:00Z', '2026-10-20T12:00:00Z', 'Everyone'),
            },
            [
                ['Status', 'Off'],
                ['Rollout', '100%'],
                ['Started', '1 Oct, 44 days ago'],
                ['Ended', '20 Oct, after 19 days'],
            ],
        ],
        [
            'the current step names its audience and the next change',
            {
                lane: flagLane(true, { percent: 50, who: 'All users' }),
                step: step('2026-11-03T12:00:00Z', '2026-11-14T12:00:00Z', '50%'),
                next: step('2026-11-20T12:00:00Z', '2026-12-01T12:00:00Z', 'Everyone', true),
            },
            [
                ['Status', 'Live'],
                ['Rollout', '50% of all users'],
                ['Started', '3 Nov, 11 days ago'],
                ['Next', '100% on 20 Nov'],
            ],
        ],
    ])('%s', (_name, props, expected) => {
        expect(laneCardFacts(props)).toEqual(expected)
    })
})
