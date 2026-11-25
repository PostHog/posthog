import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import {
    followedSendsNote,
    impactFunnelState,
    impactLift,
    impactSteps,
    stepBarPercents,
    untrackedSendsNote,
} from './impactSteps'

const impact: TransactionalEmailImpactApi = {
    sent: 100,
    delivered: 90,
    opened: 60,
    clicked: 20,
    not_clicked: 72,
    untracked: 0,
    clicks_untracked: 0,
    window_days: 7,
    after_click: { sends: 16, converted: 4 },
    without_click: { sends: 50, converted: 1 },
}
const nothingRecorded: TransactionalEmailImpactApi = {
    ...impact,
    sent: 0,
    delivered: 0,
    opened: 0,
    clicked: 0,
    not_clicked: 0,
}

const untracked: TransactionalEmailImpactApi = {
    ...impact,
    opened: 0,
    clicked: 0,
    not_clicked: 0,
    untracked: 100,
    after_click: { sends: 0, converted: 0 },
    without_click: { sends: 0, converted: 0 },
}

describe('impactSteps', () => {
    it.each([
        ['every send went out tracked', impact, null],
        [
            'every send went out untracked',
            untracked,
            "100 sends in this period went out with tracking off, so their opens and clicks aren't counted.",
        ],
        [
            'some sends went out untracked',
            { ...impact, untracked: 1200 },
            "1,200 sends in this period went out with tracking off, so their opens and clicks aren't counted.",
        ],
        [
            'one send went out untracked',
            { ...impact, untracked: 1 },
            "1 send in this period went out with tracking off, so its opens and clicks aren't counted.",
        ],
        [
            'some sends went out with click tracking off',
            { ...impact, not_clicked: 40, clicks_untracked: 30, without_click: { sends: 30, converted: 1 } },
            "30 sends in this period went out with click tracking off, so their clicks aren't counted.",
        ],
        [
            'sends went out with tracking off and with click tracking off',
            { ...impact, untracked: 2, clicks_untracked: 1 },
            "2 sends in this period went out with tracking off, so their opens and clicks aren't counted. 1 send in this period went out with click tracking off, so its clicks aren't counted.",
        ],
        [
            'an older API answers without the click tracking count',
            { ...impact, untracked: 2, clicks_untracked: undefined as unknown as number },
            "2 sends in this period went out with tracking off, so their opens and clicks aren't counted.",
        ],
    ])('notes the untracked sends when %s', (_, data, expected) => {
        expect(untrackedSendsNote(data)).toBe(expected)
    })

    it.each([
        ['a request is in flight over an earlier answer', impact, true, null, 'loading'],
        ['nothing has answered yet', null, false, null, 'loading'],
        ['the request failed', impact, false, 'Server error', 'error'],
        ['nothing was recorded in the period', nothingRecorded, false, null, 'empty'],
        ['only untracked sends were counted in the period', { ...nothingRecorded, untracked: 3 }, false, null, 'empty'],
        ['ready when clicks arrived before their sends', { ...nothingRecorded, clicked: 2 }, false, null, 'ready'],
        ['ready when opens arrived before their sends', { ...nothingRecorded, opened: 3 }, false, null, 'ready'],
        ['sends answered', impact, false, null, 'ready'],
    ] as const)('shows the funnel as %s', (_, data, loading, error, expected) => {
        expect(impactFunnelState(data, loading, error)).toBe(expected)
    })

    it('shows each step as a count, and only the conversion as a share of the clicked sends it could follow', () => {
        const steps = impactSteps(impact, 'plan upgraded')

        expect(steps.map((step) => [step.label, step.value, step.share, step.missing])).toEqual([
            ['Sent', 100, null, undefined],
            ['Delivered', 90, null, undefined],
            ['Opened', 60, null, undefined],
            ['Clicked', 20, null, undefined],
            ['Started a session', null, null, 'Needs link tagging'],
            ['plan upgraded', 4, 0.25, undefined],
        ])
        expect(steps[5]).toMatchObject({ shareOf: '16 followed', shareDetail: expect.stringContaining('16 of 20') })
        expect(impactSteps({ ...impact, after_click: { sends: 20, converted: 4 } }, 'plan upgraded')[5]).toMatchObject({
            share: 0.2,
            shareOf: 'clicked',
        })
    })

    it('draws each bar against the tallest step, so opens and clicks show before their sends', () => {
        const percents = stepBarPercents(impactSteps({ ...nothingRecorded, opened: 4, clicked: 1 }, 'plan upgraded'))

        expect(percents.slice(0, 4)).toEqual([0, 0, 100, 25])
    })

    it('asks for an event until one is picked', () => {
        const steps = impactSteps({ ...impact, after_click: null, without_click: null }, null)

        expect(steps[5]).toMatchObject({ label: 'Converted', value: null, missing: 'Pick an event' })
    })

    it.each([
        [
            'every send went out untracked',
            untracked,
            [null, 'Tracking off'],
            [null, 'Tracking off'],
            [null, 'Tracking off', 'This counts conversions after a click. Every send in this period went out'],
        ],
        [
            'no tracked send was clicked',
            { ...impact, clicked: 0, after_click: { sends: 0, converted: 0 } },
            [60, undefined],
            [0, undefined],
            [null, 'No clicks', 'This counts conversions after a click, and no clicks were recorded in this period.'],
        ],
        [
            'no clicked send could be followed',
            { ...impact, after_click: { sends: 0, converted: 0 } },
            [60, undefined],
            [20, undefined],
            [null, 'None followed', "PostHog couldn't tie any of the 20 clicked sends"],
        ],
        [
            'the one clicked send could not be followed',
            { ...impact, clicked: 1, after_click: { sends: 0, converted: 0 } },
            [60, undefined],
            [1, undefined],
            [null, 'None followed', "PostHog couldn't tie the clicked send in this period to a person."],
        ],
        [
            'every counted send went out untracked but an open was recorded',
            { ...untracked, opened: 1 },
            [1, undefined],
            [null, 'Tracking off'],
            [
                null,
                'Tracking off',
                'This counts conversions after a click. Every send in this period went out with click',
            ],
        ],
        [
            'an older API answers without the click tracking count and every send went out untracked',
            {
                ...untracked,
                opened: 1,
                not_clicked: 90,
                without_click: impact.without_click,
                clicks_untracked: undefined as unknown as number,
            },
            [1, undefined],
            [null, 'Tracking off'],
            [
                null,
                'Tracking off',
                'This counts conversions after a click. Every send in this period went out with click',
            ],
        ],
        [
            'every send went out with click tracking off',
            {
                ...impact,
                clicked: 0,
                not_clicked: 0,
                clicks_untracked: 100,
                after_click: { sends: 0, converted: 0 },
                without_click: { sends: 0, converted: 0 },
            },
            [60, undefined],
            [null, 'Tracking off'],
            [
                null,
                'Tracking off',
                'This counts conversions after a click. Every send in this period went out with click',
            ],
        ],
        [
            'some sends went out with click tracking off and nobody clicked',
            { ...impact, clicked: 0, not_clicked: 50, clicks_untracked: 40, after_click: { sends: 0, converted: 0 } },
            [60, undefined],
            [0, undefined],
            [null, 'No clicks', 'This counts conversions after a click, and no clicks were recorded'],
        ],
        [
            'every counted send went out untracked but a click was recorded',
            { ...untracked, clicked: 3 },
            [0, undefined],
            [3, undefined],
            [null, 'None followed', "PostHog couldn't tie any of the 3 clicked sends"],
        ],
        [
            'some sends went out untracked and nobody opened or clicked',
            { ...untracked, not_clicked: 50, untracked: 40, without_click: impact.without_click },
            [0, undefined],
            [0, undefined],
            [null, 'No clicks', 'This counts conversions after a click, and no clicks were recorded'],
        ],
    ] as const)('says why a step has no data when %s', (_, data, opened, clicked, converted) => {
        const steps = impactSteps(data, 'plan upgraded')
        const [, , openedStep, clickedStep, , convertedStep] = steps

        expect([openedStep.value, openedStep.missing]).toEqual(opened)
        expect([clickedStep.value, clickedStep.missing]).toEqual(clicked)
        expect([convertedStep.label, convertedStep.value, convertedStep.missing]).toEqual([
            'plan upgraded',
            converted[0],
            converted[1],
        ])
        expect(convertedStep.missingDetail?.slice(0, converted[2].length)).toBe(converted[2])
    })

    it.each([
        [
            'every send is followed',
            { ...impact, after_click: { sends: 20, converted: 4 }, without_click: { sends: 72, converted: 1 } },
            null,
        ],
        [
            'some clicked sends are not',
            { ...impact, without_click: { sends: 72, converted: 1 } },
            'Counted over 16 of 20 clicked sends:',
        ],
        [
            'both groups fall short',
            impact,
            'Counted over 16 of 20 clicked sends and 50 of 72 delivered sends with no recorded click:',
        ],
        [
            'some sends went out untracked and only unclicked sends fall short',
            {
                ...impact,
                untracked: 40,
                not_clicked: 30,
                after_click: { sends: 20, converted: 4 },
                without_click: { sends: 25, converted: 1 },
            },
            'Counted over 25 of 30 delivered sends with no recorded click:',
        ],
    ])('names the sends the lift counts when %s', (_, data, start) => {
        const note = followedSendsNote(data)

        expect(start === null ? note : note?.slice(0, start.length)).toBe(start)
    })

    it('compares clicked against not clicked, and leaves out a side with no sends', () => {
        expect(impactLift(impact)).toEqual({ clicked: 0.25, notClicked: 0.02 })
        expect(impactLift({ ...impact, after_click: { sends: 0, converted: 0 } })).toEqual({
            clicked: null,
            notClicked: 0.02,
        })
        expect(impactLift({ ...impact, after_click: null, without_click: null })).toBeNull()
    })
})
