import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import { clicksTracked, followedSendsNote, impactFunnelState, impactLift, impactSteps } from './impactSteps'

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
        ['every send went out tracked', impact, true],
        ['every send went out untracked', untracked, false],
        ['some sends went out untracked', { ...impact, untracked: 40 }, true],
        ['tracked sends nobody opened or clicked', { ...impact, opened: 0, clicked: 0 }, true],
        ['nothing was sent', { ...impact, sent: 0 }, true],
    ])('reads click tracking when %s', (_, data, expected) => {
        expect(clicksTracked(data)).toBe(expected)
    })

    it.each([
        ['a request is in flight over an earlier answer', impact, true, null, 'loading'],
        ['nothing has answered yet', null, false, null, 'loading'],
        ['the request failed', impact, false, 'Server error', 'error'],
        ['nothing was sent in the period', { ...impact, sent: 0 }, false, null, 'empty'],
        ['sends answered', impact, false, null, 'ready'],
    ] as const)('shows the funnel as %s', (_, data, loading, error, expected) => {
        expect(impactFunnelState(data, loading, error)).toBe(expected)
    })

    it('ends with the conversion event as a share of the clicked sends it could follow', () => {
        const steps = impactSteps(impact, 'plan upgraded')

        expect(steps.map((step) => [step.label, step.value, step.share, step.missing])).toEqual([
            ['Sent', 100, null, undefined],
            ['Delivered', 90, 0.9, undefined],
            ['Opened', 60, 60 / 90, undefined],
            ['Clicked', 20, 20 / 60, undefined],
            ['Started a session', null, null, 'Needs link tagging'],
            ['plan upgraded', 4, 0.25, undefined],
        ])
        expect(steps[5]).toMatchObject({ shareOf: '16 followed', shareDetail: expect.stringContaining('16 of 20') })
        expect(impactSteps({ ...impact, after_click: { sends: 20, converted: 4 } }, 'plan upgraded')[5]).toMatchObject({
            share: 0.2,
            shareOf: 'clicked',
        })
    })

    it('compares clicks to delivered when they outnumber opens', () => {
        const steps = impactSteps({ ...impact, opened: 10 }, 'plan upgraded')

        expect(steps[3]).toMatchObject({ value: 20, share: 20 / 90, shareOf: 'delivered' })
    })

    it('asks for an event until one is picked', () => {
        const steps = impactSteps({ ...impact, after_click: null, without_click: null }, null)

        expect(steps[5]).toMatchObject({ label: 'Converted', value: null, missing: 'Pick an event' })
    })

    it('counts conversions from the send against delivered when clicks are not tracked', () => {
        const steps = impactSteps({ ...untracked, without_click: { sends: 90, converted: 1 } }, 'plan upgraded')

        expect(steps.slice(2, 5).map((step) => step.missing)).toEqual(['Not tracked', 'Not tracked', 'Not tracked'])
        expect(steps[5]).toMatchObject({ value: 1, share: 1 / 90, shareOf: 'delivered' })
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
        ['both groups fall short', impact, 'Counted over 16 of 20 clicked sends and 50 of 72 sends nobody clicked:'],
        [
            'untracked sends fall short',
            { ...untracked, without_click: { sends: 50, converted: 1 } },
            'Counted over 50 of 90 delivered sends:',
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
