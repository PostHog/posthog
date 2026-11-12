import { metricAboutCopy, targetAboutCopy } from './aboutCopy'
import type { CellModel, MetricCardModel, MetricDef, StatsSettings } from './detailModel'

const BAYES: StatsSettings = { method: 'bayes', level: 0.95, alpha: 0.05 }
const FREQ: StatsSettings = { method: 'freq', level: 0.95, alpha: 0.05 }

function def(overrides: Partial<MetricDef> = {}): MetricDef {
    return {
        uuid: 'm-1',
        name: 'Checkout completed',
        goal: 'increase',
        metricType: 'funnel',
        role: 'primary',
        kind: 'rate',
        rateVerb: 'converted',
        quantile: null,
        ...overrides,
    }
}

const baseline: CellModel = {
    key: 'control',
    colorIndex: 0,
    isBaseline: true,
    samples: 2281,
    value: 0.1249,
    numerator: 285,
    delta: null,
    interval: null,
    chanceToWin: null,
    pValue: null,
    significant: false,
    better: null,
    side: 'none',
}

function variant(overrides: Partial<CellModel> = {}): CellModel {
    return {
        key: 'start-trial',
        colorIndex: 1,
        isBaseline: false,
        samples: 2265,
        value: 0.1404,
        numerator: 318,
        delta: 0.124,
        interval: [0.03, 0.218],
        chanceToWin: 0.991,
        pValue: null,
        significant: true,
        better: true,
        side: 'good',
        ...overrides,
    }
}

function card(cell: CellModel, metric: MetricDef = def()): MetricCardModel {
    return { def: metric, state: 'ready', baseline, variants: [cell], leaderKey: cell.key, scale: 0.25, error: null }
}

describe('aboutCopy', () => {
    it('says a Bayesian chance to win on a lower-is-better metric is the chance of a lower value', () => {
        const cell = variant({
            chanceToWin: 0.64,
            delta: -0.062,
            interval: [-0.381, 0.257],
            significant: false,
            better: true,
            side: 'none',
        })
        const copy = metricAboutCopy({
            what: 'chance',
            card: card(cell, def({ goal: 'decrease', name: 'Support tickets opened' })),
            variantKey: cell.key,
            settings: BAYES,
            runAt: null,
        })
        expect(copy?.title).toBe('64.0% chance to win')
        expect(copy?.lead).toBe(
            "Lower is better here. Given the data so far, there's a 64.0% chance start-trial has a lower conversion rate than control."
        )
        expect(copy?.rows.find((row) => row.label === 'Goal')?.value).toBe('Lower is better')
        expect(copy?.figure?.caption).toBe('Change vs control · 95% credible interval')
    })

    it('explains Bayesian significance by the chance to win, not by the interval', () => {
        const cell = variant({ chanceToWin: 0.96, interval: [-0.01, 0.2], side: 'none', significant: true })
        const copy = metricAboutCopy({
            what: 'delta',
            card: card(cell),
            variantKey: cell.key,
            settings: BAYES,
            runAt: null,
        })
        expect(copy?.rows.find((row) => row.label === 'Significant')).toEqual({
            label: 'Significant',
            value: 'Yes',
            sub: 'chance to win is above 95%',
        })
        expect(copy?.lead).toContain("There's a 95% chance the real change is between −1.0% and +20.0%.")
    })

    it('reads a significant Frequentist drop against the configured cut-off', () => {
        const cell = variant({
            delta: -0.14,
            interval: [-0.248, -0.032],
            chanceToWin: null,
            pValue: 0.009,
            significant: true,
            better: false,
            side: 'bad',
        })
        const copy = metricAboutCopy({
            what: 'chance',
            card: card(cell),
            variantKey: cell.key,
            settings: FREQ,
            runAt: null,
        })
        expect(copy?.what).toBe('p_value')
        expect(copy?.tone).toBe('bad')
        expect(copy?.lead).toBe(
            "If start-trial and control really performed the same, a difference at least this big would show up 0.9% of the time. That's under the 0.05 cut-off, so the drop is significant."
        )
        expect(copy?.rows.find((row) => row.label === 'Significant')?.sub).toBe('the whole range is below 0')
        expect(copy?.figure?.caption).toBe('Change vs control · 95% confidence interval')
    })

    it('puts the right article before a chance read aloud', () => {
        const cell = variant({ chanceToWin: 0.874, significant: false, side: 'none' })
        const copy = metricAboutCopy({
            what: 'chance',
            card: card(cell),
            variantKey: cell.key,
            settings: BAYES,
            runAt: null,
        })
        expect(copy?.lead).toContain("there's an 87.4% chance")
    })

    it('states a Frequentist interval as a confidence interval, not a probability', () => {
        const cell = variant({
            chanceToWin: null,
            pValue: 0.2,
            significant: false,
            interval: [-0.05, 0.2],
            side: 'none',
        })
        const copy = metricAboutCopy({
            what: 'delta',
            card: card(cell),
            variantKey: cell.key,
            settings: FREQ,
            runAt: null,
        })
        expect(copy?.lead).toContain('The 95% confidence interval for the real change runs from −5.0% to +20.0%.')
        expect(copy?.foot).toContain('A variant is significant when the whole range sits on one side of 0.')
    })

    it('explains the baseline with its own counts', () => {
        const copy = metricAboutCopy({
            what: 'value',
            card: card(variant()),
            variantKey: 'control',
            settings: BAYES,
            runAt: null,
        })
        expect(copy?.title).toBe('control is the baseline')
        expect(copy?.lead).toContain('285 of the 2,281 people who saw control converted (12.49%).')
    })

    it('gives the days to go from the pace', () => {
        const copy = targetAboutCopy({
            progress: {
                current: 1242,
                recommended: 2200,
                state: 'to_go',
                daysToGo: 4,
                perDay: 311,
                daysRunning: 4,
                minimumEffect: 5,
                fill: 0.56,
            },
            name: 'Invite reminder email',
            runningFor: '4 days',
        })
        expect(copy.title).toBe('~4 days to go')
        expect(copy.lead).toBe(
            "1,242 of the 2,200 recommended exposures. At about 311 a day, that's about 4 more days."
        )
    })
})
