import { ADVENT_LAST_DAY, ADVENT_QUESTION_DAYS, ADVENT_QUESTIONS } from './adventContent'
import { AdventProgress } from './adventGraph'

// pinned: the localStorage key of each person's opened doors. Renaming it resets them.
export const PROGRESS_STORAGE_KEY = 'workflows-advent-calendar-progress'

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value)
}

function isAdventDay(day: unknown): day is number {
    return Number.isInteger(day) && (day as number) >= 1 && (day as number) <= ADVENT_LAST_DAY
}

function isAdventAnswer(answer: [string, unknown]): answer is [string, string] {
    return !!ADVENT_QUESTIONS[Number(answer[0])]?.options.some((option) => option.id === answer[1])
}

function cleanProgress(opened: unknown[], answers: unknown): AdventProgress {
    return {
        opened: [...new Set(opened.filter(isAdventDay))],
        answers: Object.fromEntries(Object.entries(isRecord(answers) ? answers : {}).filter(isAdventAnswer)),
    }
}

export function reachableProgress({ opened, answers }: AdventProgress): AdventProgress {
    const unanswered = ADVENT_QUESTION_DAYS.find((day) => opened.includes(day) && !answers[day])
    return { opened: opened.filter((day) => unanswered === undefined || day < unanswered), answers }
}

export function storedProgressByUser(): unknown {
    try {
        return JSON.parse(window.localStorage.getItem(PROGRESS_STORAGE_KEY) ?? 'null')
    } catch {
        return null
    }
}

export function cleanProgressByUser(value: unknown): Record<string, AdventProgress> {
    return Object.fromEntries(
        Object.entries(isRecord(value) ? value : {}).flatMap(([uuid, progress]) =>
            isRecord(progress) && Array.isArray(progress.opened)
                ? [[uuid, cleanProgress(progress.opened, progress.answers)]]
                : []
        )
    )
}
