import { ADVENT_LAST_DAY } from './adventContent'
import { drawAdventRewards } from './adventDraw'
import { buildAdventGraph } from './adventGraph'

const ALICE = '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01'
const BOB = '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e02'

const ALL_DAYS = Array.from({ length: ADVENT_LAST_DAY }, (_, index) => index + 1)

function everyRewardId(seed: string): string[] {
    const { trail, detours } = drawAdventRewards(seed)
    return [...Object.values(trail), ...Object.values(detours)].map((reward) => reward.id)
}

describe('drawAdventRewards', () => {
    it('gives one person the same hedgehogs every time', () => {
        expect(drawAdventRewards(ALICE)).toEqual(drawAdventRewards(ALICE))
    })

    it('gives two people different hedgehogs', () => {
        expect(everyRewardId(ALICE)).not.toEqual(everyRewardId(BOB))
    })

    it.each([ALICE, BOB, ''])('never shows the same hedgehog twice for seed %j', (seed) => {
        const ids = everyRewardId(seed)
        expect(new Set(ids).size).toBe(ids.length)
    })

    it.each([ALICE, BOB])('keeps the fixed doors for seed %s', (seed) => {
        const progress = {
            opened: ALL_DAYS,
            answers: { 2: 'tim', 5: 'yes', 10: 'tabs', 13: 'dark', 18: 'yes', 21: 'tea' },
        }
        const graph = buildAdventGraph(progress, ADVENT_LAST_DAY, drawAdventRewards(seed))
        const rewardOn = (day: number): string[] =>
            graph.doors.filter((door) => door.day === day).map((door) => door.reward?.name ?? '')

        expect(rewardOn(2)).toEqual(['Tim Glaser'])
        expect(rewardOn(24)).toEqual(['Heart'])
        expect(graph.doors.filter((door) => door.reward?.name === 'Heart')).toHaveLength(1)
        expect(graph.doors.every((door) => door.reward)).toBe(true)
    })
})
