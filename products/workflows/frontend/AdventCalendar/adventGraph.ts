import {
    ADVENT_LAST_DAY,
    ADVENT_QUESTIONS,
    ADVENT_YEAR,
    AdventOption,
    AdventQuestion,
    adventQuestionBefore,
    AdventReward,
} from './adventContent'
import type { AdventRewards } from './adventDraw'

export const ADVENT_PICTURE = { width: 1200, height: 675 }
export const ADVENT_DOOR_SIZE = 56

export interface AdventProgress {
    opened: number[]
    answers: Record<number, string>
}

export const EMPTY_ADVENT_PROGRESS: AdventProgress = { opened: [], answers: {} }

export function mergeAdventProgress(first: AdventProgress, then: AdventProgress): AdventProgress {
    return {
        opened: [...new Set([...first.opened, ...then.opened])].sort((x, y) => x - y),
        answers: { ...then.answers, ...first.answers },
    }
}

export type AdventDoorStatus = 'locked' | 'ready' | 'open'
export type AdventSide = 'left' | 'right' | 'top' | 'bottom'

export interface AdventPoint {
    x: number
    y: number
}

export interface AdventDoor extends AdventPoint {
    id: string
    day: number
    row: number
    status: AdventDoorStatus
    lockReason: 'date' | 'order' | null
    reward: AdventReward | null
    question: AdventQuestion | null
    answer: AdventOption | null
}

export interface AdventLink {
    id: string
    from: string
    to: string
    fromSide: AdventSide
    toSide: AdventSide
    walked: boolean
}

export interface AdventGraph {
    trigger: AdventPoint
    doors: AdventDoor[]
    links: AdventLink[]
}

export const ADVENT_TRIGGER_ID = 'trigger'

const DOOR_COLORS = ['var(--brand-red)', 'var(--brand-blue)', 'var(--success)', 'var(--warning)']

export function adventDayColor(day: number): string {
    return DOOR_COLORS[day % DOOR_COLORS.length]
}

export function adventDoorColor(door: AdventDoor): string {
    return door.status === 'locked' ? 'var(--border-bold)' : adventDayColor(door.day)
}

const DAYS = Array.from({ length: ADVENT_LAST_DAY }, (_, index) => index + 1)

const TRAIL_COLUMNS = 8
const TRAIL_LANE_OFFSET = 40
const TRAIL_ORIGIN = { x: 195, y: 137 }
const TRAIL_GAP = { x: 125, y: 205 }
const HOG_SIZES = [70, 82, 96]

type TrailLane = 'upper' | 'lower'
const LANES: TrailLane[] = ['upper', 'lower']

function sides(from: AdventPoint, to: AdventPoint): Pick<AdventLink, 'fromSide' | 'toSide'> {
    const dx = to.x - from.x
    const dy = to.y - from.y
    if (Math.abs(dx) >= Math.abs(dy) * 0.8) {
        return dx >= 0 ? { fromSide: 'right', toSide: 'left' } : { fromSide: 'left', toSide: 'right' }
    }
    return dy >= 0 ? { fromSide: 'bottom', toSide: 'top' } : { fromSide: 'top', toSide: 'bottom' }
}

function answerOf(question: AdventQuestion | null, answerId: string | undefined): AdventOption | null {
    return question?.options.find((option) => option.id === answerId) ?? null
}

function statusOf(day: number, progress: AdventProgress, today: number): Pick<AdventDoor, 'status' | 'lockReason'> {
    if (progress.opened.includes(day)) {
        return { status: 'open', lockReason: null }
    }
    if (day > today) {
        return { status: 'locked', lockReason: 'date' }
    }
    return day === DAYS.find((candidate) => !progress.opened.includes(candidate))
        ? { status: 'ready', lockReason: null }
        : { status: 'locked', lockReason: 'order' }
}

function onOneLane(source: AdventDoor | null, target: AdventDoor): boolean {
    const [from, to] = [source?.id.split('-')[2], target.id.split('-')[2]]
    return !from || !to || from === to
}

function trailPoint(day: number): AdventPoint & { row: number } {
    const index = day - 1
    const row = Math.floor(index / TRAIL_COLUMNS)
    const step = index % TRAIL_COLUMNS
    const column = row % 2 === 0 ? step : TRAIL_COLUMNS - 1 - step
    return {
        row,
        x: TRAIL_ORIGIN.x + column * TRAIL_GAP.x,
        y: TRAIL_ORIGIN.y + row * TRAIL_GAP.y + Math.round(8 * Math.sin(index * 1.1)),
    }
}

export function adventDoorGround(door: AdventPoint): AdventPoint {
    return { x: door.x + ADVENT_DOOR_SIZE / 2, y: door.y + ADVENT_DOOR_SIZE + 2 }
}

export function adventDoorCenter(door: AdventPoint): AdventPoint {
    return { x: door.x + ADVENT_DOOR_SIZE / 2, y: door.y + ADVENT_DOOR_SIZE / 2 }
}

export function adventPictureAt(point: AdventPoint): { left: string; top: string } {
    return { left: `${(point.x / ADVENT_PICTURE.width) * 100}%`, top: `${(point.y / ADVENT_PICTURE.height) * 100}%` }
}

export function adventHogSize(door: AdventDoor): number {
    return HOG_SIZES[door.row] * (door.reward?.isPortrait ? 0.8 : 1)
}

function doorsOf(day: number, progress: AdventProgress, today: number, rewards: AdventRewards): AdventDoor[] {
    const point = trailPoint(day)
    const status = statusOf(day, progress, today)
    const questionDay = adventQuestionBefore(day)

    if (questionDay === null) {
        const question = ADVENT_QUESTIONS[day] ?? null
        const answer = answerOf(question, progress.answers[day])
        return [
            {
                ...point,
                ...status,
                id: `door-${day}`,
                day,
                reward: answer?.reward ?? rewards.trail[day] ?? null,
                question,
                answer,
            },
        ]
    }

    const question = ADVENT_QUESTIONS[questionDay]
    const answer = answerOf(question, progress.answers[questionDay])
    const taken: TrailLane | null = answer ? LANES[question.options.indexOf(answer)] : null
    return LANES.filter((lane) => taken === null || taken === lane).map(
        (lane): AdventDoor => ({
            day,
            row: point.row,
            x: point.x,
            y: point.y + (lane === 'upper' ? -TRAIL_LANE_OFFSET : TRAIL_LANE_OFFSET),
            ...(taken === null && status.status === 'ready'
                ? ({ status: 'locked', lockReason: 'order' } as const)
                : status),
            id: `door-${day}-${lane}`,
            reward: (lane === 'upper' ? rewards.trail[day] : rewards.detours[day]) ?? null,
            question: null,
            answer: null,
        })
    )
}

function linksInto(current: AdventDoor[], previous: AdventDoor[], trigger: AdventPoint): AdventLink[] {
    const sources = previous.length ? previous : [null]
    return current.flatMap((target) =>
        sources
            .filter((source) => onOneLane(source, target))
            .map(
                (source): AdventLink => ({
                    id: `${source?.id ?? ADVENT_TRIGGER_ID}>${target.id}`,
                    from: source?.id ?? ADVENT_TRIGGER_ID,
                    to: target.id,
                    ...sides(source ?? trigger, target),
                    walked: target.status === 'open' && (!source || source.status === 'open'),
                })
            )
    )
}

export function buildAdventGraph(progress: AdventProgress, today: number, rewards: AdventRewards): AdventGraph {
    const first = trailPoint(1)
    const trigger = { x: first.x - TRAIL_GAP.x, y: first.y }
    const doors: AdventDoor[] = []
    const links: AdventLink[] = []
    let previous: AdventDoor[] = []

    for (const day of DAYS) {
        const current = doorsOf(day, progress, today, rewards)
        links.push(...linksInto(current, previous, trigger))
        doors.push(...current)
        previous = current
    }
    return { trigger, doors, links }
}

export function openDoors(graph: AdventGraph): AdventDoor[] {
    return graph.doors.filter((door) => door.status === 'open')
}

export function adventWeekday(day: number): string {
    return new Date(ADVENT_YEAR, 11, day).toLocaleDateString('en-US', { weekday: 'long' })
}
