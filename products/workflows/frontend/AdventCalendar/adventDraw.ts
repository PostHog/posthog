import { ADVENT_LAST_DAY, ADVENT_QUESTIONS, adventQuestionBefore, AdventReward } from './adventContent'
import { ADVENT_HEART_HOGGY, ADVENT_HOGGY_POOL } from './adventHoggies'

export interface AdventRewards {
    trail: Record<number, AdventReward>
    detours: Record<number, AdventReward>
}

const LAST_REWARD: AdventReward = {
    ...ADVENT_HEART_HOGGY,
    line: 'That was all 24 doors. Thank you for opening them with us.',
}

const DAYS = Array.from({ length: ADVENT_LAST_DAY - 1 }, (_, index) => index + 1)
const TRAIL_DAYS = DAYS.filter((day) => !ADVENT_QUESTIONS[day]?.options.some((option) => option.reward))
const DETOUR_DAYS = DAYS.filter((day) => adventQuestionBefore(day) !== null)

function hashOf(text: string): number {
    let hash = 2166136261
    for (let index = 0; index < text.length; index++) {
        hash = Math.imul(hash ^ text.charCodeAt(index), 16777619)
    }
    return hash >>> 0
}

function randomFrom(seed: number): () => number {
    let state = seed
    return () => {
        state = (state + 0x6d2b79f5) >>> 0
        let mixed = Math.imul(state ^ (state >>> 15), 1 | state)
        mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed
        return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296
    }
}

function shuffled<T>(items: T[], random: () => number): T[] {
    const result = [...items]
    for (let index = result.length - 1; index > 0; index--) {
        const other = Math.floor(random() * (index + 1))
        ;[result[index], result[other]] = [result[other], result[index]]
    }
    return result
}

export function drawAdventRewards(seed: string): AdventRewards {
    const picks = shuffled(ADVENT_HOGGY_POOL, randomFrom(hashOf(seed)))
    const trail = Object.fromEntries(TRAIL_DAYS.map((day, index) => [day, picks[index]]))
    const detours = Object.fromEntries(DETOUR_DAYS.map((day, index) => [day, picks[TRAIL_DAYS.length + index]]))
    return { trail: { ...trail, [ADVENT_LAST_DAY]: LAST_REWARD }, detours }
}
