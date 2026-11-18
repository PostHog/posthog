import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import {
    emptyPeriodMessage,
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
    not_clicked: 90,
    untracked: 100,
    after_click: { sends: 0, converted: 0 },
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

    it('says nobody was sent when no send went out, tracked or not', () => {
        expect(emptyPeriodMessage(nothingRecorded)).toBe('Nobody was sent this email in this period.')
    })

    it('draws each bar against the tallest step, so opens and clicks show before their sends', () => {
        const percents = stepBarPercents(impactSteps({ ...nothingRecorded, opened: 4, clicked: 1 }, 'plan upgraded'))

        expect(percents.slice(0, 4)).toEqual([0, 0, 100, 25])
    })

    it('asks for an event until one is picked', () => {
        const steps = impactSteps({ ...impact, after_click: null, without_click: null }, null)

        expect(steps[5]).toMatchObject({ label: 'Converted', value: null, missing: 'Pick an event' })
    })

    it('shows opens, clicks and conversions after a click as recorded when every send went out untracked', () => {
        const steps = impactSteps(untracked, 'plan upgraded')

        expect(steps.map((step) => [step.label, step.value, step.missing])).toEqual([
            ['Sent', 100, undefined],
            ['Delivered', 90, undefined],
            ['Opened', 0, undefined],
            ['Clicked', 0, undefined],
            ['Started a session', null, 'Needs link tagging'],
            ['plan upgraded', 0, undefined],
        ])
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
            'every send went out untracked and some unclicked sends fall short',
            { ...untracked, without_click: { sends: 50, converted: 1 } },
            'Counted over 50 of 90 delivered sends with no recorded click:',
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
