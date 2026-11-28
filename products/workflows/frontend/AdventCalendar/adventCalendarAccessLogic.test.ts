import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'

import { initKeaTests } from '~/test/init'
import type { AppContext } from '~/types'

import { adventCalendarAccessLogic } from './adventCalendarAccessLogic'

const FLAG = FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR

type FlagsCallback = (flags: string[], variants: Record<string, string | boolean>, context?: object) => void

type Step =
    | { outcome: 'failed' | 'succeeded' | 'no outcome'; enabledFlags: Record<string, boolean> }
    | { outcome: 'tab hidden' }

type Visit = {
    pageFlags: Record<string, boolean | string> | null | 'no page object'
    errorsBeforeMount?: unknown
    steps: Step[]
}

const failed = (enabledFlags: Record<string, boolean> = {}): Step => ({ outcome: 'failed', enabledFlags })
const succeeded = (enabledFlags: Record<string, boolean> = {}): Step => ({ outcome: 'succeeded', enabledFlags })
const noOutcome = (enabledFlags: Record<string, boolean> = {}): Step => ({ outcome: 'no outcome', enabledFlags })
const tabHidden: Step = { outcome: 'tab hidden' }

type View = 'waiting' | 'calendar' | 'not found'

type FlagsReply =
    | 'blocked'
    | 'answers on'
    | 'answers off'
    | 'unrelated error, answers on'
    | 'unrelated error, answers off'

type DecisionRow = {
    page: 'on' | 'off' | 'left out' | 'absent'
    persisted: 'persisted' | 'not persisted'
    cached: 'first visit' | 'stored without it' | 'stored on' | 'stored off'
    load: 'not yet' | FlagsReply | `${FlagsReply}, then ${FlagsReply}`
    timeout: 'before timeout' | 'after timeout' | 'flags arrived'
    sees: View
}

type DecisionTableRow = [
    DecisionRow['page'],
    DecisionRow['persisted'],
    DecisionRow['cached'],
    DecisionRow['load'],
    DecisionRow['timeout'],
    DecisionRow['sees'],
]

const DECISION_TABLE: DecisionTableRow[] = [
    ['on', 'not persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['on', 'not persisted', 'first visit', 'not yet', 'after timeout', 'not found'],
    ['on', 'not persisted', 'first visit', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'first visit', 'answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'first visit', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'first visit', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'first visit', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'first visit', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'first visit', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['on', 'not persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['on', 'not persisted', 'stored without it', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored without it', 'answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored without it', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored without it', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored without it', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored without it', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored without it', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['on', 'not persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['on', 'not persisted', 'stored on', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored on', 'answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored on', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored on', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored on', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored on', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored on', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['on', 'not persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['on', 'not persisted', 'stored off', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored off', 'answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored off', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored off', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored off', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored off', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored off', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['on', 'persisted', 'first visit', 'not yet', 'after timeout', 'calendar'],
    ['on', 'persisted', 'first visit', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'first visit', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'first visit', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['on', 'persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['on', 'persisted', 'stored without it', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored without it', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored without it', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['on', 'persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['on', 'persisted', 'stored on', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored on', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored on', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['on', 'persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['on', 'persisted', 'stored off', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored off', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored off', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['off', 'not persisted', 'first visit', 'not yet', 'after timeout', 'not found'],
    ['off', 'not persisted', 'first visit', 'blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'first visit', 'answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'first visit', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'first visit', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'first visit', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'first visit', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'first visit', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['off', 'not persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['off', 'not persisted', 'stored without it', 'blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored without it', 'answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored without it', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored without it', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored without it', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored without it', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored without it', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['off', 'not persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['off', 'not persisted', 'stored on', 'blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored on', 'answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored on', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored on', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored on', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored on', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored on', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['off', 'not persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['off', 'not persisted', 'stored off', 'blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored off', 'answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored off', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored off', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored off', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored off', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored off', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['left out', 'not persisted', 'first visit', 'not yet', 'after timeout', 'not found'],
    ['left out', 'not persisted', 'first visit', 'blocked', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'first visit', 'answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'first visit', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'first visit', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'first visit', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'first visit', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'first visit', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['left out', 'not persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['left out', 'not persisted', 'stored without it', 'blocked', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored without it', 'answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored without it', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored without it', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored without it', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored without it', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored without it', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['left out', 'not persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['left out', 'not persisted', 'stored on', 'blocked', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored on', 'answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored on', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored on', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored on', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored on', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored on', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['left out', 'not persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['left out', 'not persisted', 'stored off', 'blocked', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored off', 'answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored off', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored off', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['left out', 'not persisted', 'stored off', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored off', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['left out', 'not persisted', 'stored off', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'not persisted', 'first visit', 'not yet', 'after timeout', 'not found'],
    ['absent', 'not persisted', 'first visit', 'blocked', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'first visit', 'answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'first visit', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'first visit', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'first visit', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'first visit', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'first visit', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'not persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'blocked', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored without it', 'answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored without it', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored without it', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'not persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'blocked', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored on', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored on', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored on', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'not persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['absent', 'not persisted', 'stored off', 'blocked', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored off', 'answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored off', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored off', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored off', 'blocked, then answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored off', 'answers off, then blocked', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored off', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'persisted', 'first visit', 'not yet', 'after timeout', 'calendar'],
    ['absent', 'persisted', 'first visit', 'blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'first visit', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'first visit', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['absent', 'persisted', 'stored without it', 'blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored without it', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored without it', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['absent', 'persisted', 'stored on', 'blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored on', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored on', 'answers on, then blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['absent', 'persisted', 'stored off', 'blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored off', 'blocked, then answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored off', 'answers on, then blocked', 'flags arrived', 'calendar'],
]

function toView(calendarOn: boolean | undefined): View {
    return calendarOn === undefined ? 'waiting' : calendarOn ? 'calendar' : 'not found'
}

function masterView(): View {
    if (!featureFlagLogic.values.receivedFeatureFlags && !appLogic.values.featureFlagsTimedOut) {
        return 'waiting'
    }
    return featureFlagLogic.values.featureFlags[FLAG] ? 'calendar' : 'not found'
}

function sdkValueBeforeLoad({ page, cached }: DecisionRow): 'on' | 'off' | 'none' {
    if (cached === 'first visit') {
        return page === 'on' || page === 'off' ? page : 'none'
    }
    return cached === 'stored on' ? 'on' : cached === 'stored off' ? 'off' : 'none'
}

function servePage(row: DecisionRow): void {
    window.POSTHOG_APP_CONTEXT = {
        persisted_feature_flags: row.persisted === 'persisted' ? [FLAG] : [],
    } as unknown as AppContext
    if (row.page === 'absent') {
        delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
    } else {
        window.POSTHOG_USER_IDENTITY_WITH_FLAGS = {
            distinctID: 'person-1',
            featureFlags: row.page === 'left out' ? { 'other-flag': true } : { [FLAG]: row.page === 'on' },
        }
    }
    const storedOn = row.cached === 'stored on' || (row.cached === 'first visit' && row.persisted === 'persisted')
    if (row.cached !== 'first visit' || storedOn) {
        localStorage.setItem(
            'lib.logic.featureFlagLogic.featureFlags',
            JSON.stringify(storedOn ? { [FLAG]: true } : {})
        )
    }
}

function replyErrors(reply: FlagsReply): string[] {
    if (reply === 'blocked') {
        return ['connection_error']
    }
    return reply.startsWith('unrelated error') ? ['errors_while_computing_flags'] : []
}

function replyValue(reply: FlagsReply, previous: 'on' | 'off' | 'none'): 'on' | 'off' | 'none' {
    if (reply === 'blocked') {
        return previous
    }
    return reply.endsWith('answers on') ? 'on' : 'off'
}

function setTabHidden(hidden: boolean): void {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    document.dispatchEvent(new Event('visibilitychange'))
}

describe('adventCalendarAccessLogic', () => {
    let flagCallbacks: Set<FlagsCallback>
    let loadedFlags: Record<string, boolean> | null

    beforeEach(() => {
        localStorage.clear()
        flagCallbacks = new Set()
        loadedFlags = null
        jest.mocked(posthog.onFeatureFlags).mockImplementation((callback) => {
            flagCallbacks.add(callback as FlagsCallback)
            if (loadedFlags) {
                ;(callback as FlagsCallback)(Object.keys(loadedFlags), loadedFlags)
            }
            return () => flagCallbacks.delete(callback as FlagsCallback)
        })
    })

    afterEach(() => {
        setTabHidden(false)
        delete window.POSTHOG_GLOBAL_ERRORS
        delete window.POSTHOG_FEATURE_FLAGS_LOADED
        delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
        delete window.POSTHOG_APP_CONTEXT
        jest.mocked(posthog.get_property).mockReset()
    })

    function openCalendar(
        row: DecisionRow,
        opened: 'before the load' | 'after the load'
    ): { sees: View; master: View } {
        localStorage.clear()
        flagCallbacks.clear()
        loadedFlags = null
        delete window.POSTHOG_GLOBAL_ERRORS
        delete window.POSTHOG_FEATURE_FLAGS_LOADED
        jest.mocked(posthog.get_property).mockReset()
        servePage(row)
        initKeaTests()
        featureFlagLogic.mount()
        appLogic.mount()
        const logic = adventCalendarAccessLogic()

        let value = sdkValueBeforeLoad(row)
        let errors: string[] = []
        jest.mocked(posthog.get_property).mockImplementation((key) =>
            key === '$feature_flag_errors' ? errors : undefined
        )
        const answer = (reply: FlagsReply): void => {
            if (reply === 'blocked') {
                window.POSTHOG_GLOBAL_ERRORS = { onFeatureFlagsLoadError: true }
            } else {
                window.POSTHOG_FEATURE_FLAGS_LOADED = true
            }
            errors = replyErrors(reply)
            value = replyValue(reply, value)
            const enabled: Record<string, boolean> = value === 'on' ? { [FLAG]: true } : {}
            loadedFlags = enabled
            for (const callback of flagCallbacks) {
                callback(Object.keys(enabled), enabled, { errorsLoading: reply === 'blocked' })
            }
        }
        const replies = row.load === 'not yet' ? [] : (row.load.split(', then ') as FlagsReply[])

        if (opened === 'before the load') {
            logic.mount()
        }
        replies.forEach(answer)
        if (opened === 'after the load') {
            logic.mount()
        }
        if (row.timeout === 'after timeout') {
            appLogic.actions.ignoreFeatureFlags()
        }

        const result = { sees: toView(logic.values.calendarOn), master: masterView() }
        logic.unmount()
        appLogic.unmount()
        return result
    }

    describe('decision table: a persisted flag never decides off because it is rolled out to everyone, each reply comes through its own flag callback, and the timeout stops mattering once flags arrive', () => {
        it.each(DECISION_TABLE)(
            'page %s, %s, %s, flags %s, %s: sees %s',
            (page, persisted, cached, load, timeout, expected) => {
                const row: DecisionRow = { page, persisted, cached, load, timeout, sees: expected }
                const onlyBlockedReplies =
                    load !== 'not yet' && load.split(', then ').every((reply) => reply === 'blocked')
                const pageView: View | null = page === 'absent' ? null : page === 'on' ? 'calendar' : 'not found'
                const openings =
                    load === 'not yet'
                        ? (['before the load'] as const)
                        : (['before the load', 'after the load'] as const)
                for (const opened of openings) {
                    const { sees, master } = openCalendar(row, opened)
                    expect({ opened, sees }).toEqual({ opened, sees: expected })
                    expect({
                        opened,
                        sees,
                        master,
                        sameAsMasterOrPageAfterOnlyBlockedReplies:
                            sees === master || (onlyBlockedReplies && sees === pageView),
                    }).toMatchObject({ sameAsMasterOrPageAfterOnlyBlockedReplies: true })
                }
            }
        )
    })

    it.each<[string, Visit, (boolean | undefined)[]]>([
        [
            'a successful load shows the flag on',
            { pageFlags: { [FLAG]: false }, steps: [succeeded({ [FLAG]: true })] },
            [true],
        ],
        [
            'a successful load with the flag off wins over a page decision on',
            { pageFlags: { [FLAG]: true }, steps: [succeeded()] },
            [false],
        ],
        ['a failed load shows the page decision on', { pageFlags: { [FLAG]: true }, steps: [failed()] }, [true]],
        [
            'a failed load shows the page decision off over a stored flag on',
            { pageFlags: { [FLAG]: false }, steps: [failed({ [FLAG]: true })] },
            [false],
        ],
        [
            'a successful retry hides the calendar even when no enabled flag changed',
            { pageFlags: { [FLAG]: true }, steps: [failed({ 'other-flag': true }), succeeded({ 'other-flag': true })] },
            [true, false],
        ],
        [
            'a 200 after a failed load switches the tab off when the flag is off',
            { pageFlags: { [FLAG]: true }, steps: [failed({ [FLAG]: true }), succeeded()] },
            [true, false],
        ],
        [
            'a failed refresh after a successful load keeps the loaded flag over a page decision off',
            { pageFlags: { [FLAG]: false }, steps: [succeeded({ [FLAG]: true }), failed({ [FLAG]: true })] },
            [true, true],
        ],
        [
            'a successful retry while the tab is hidden shows the flag',
            { pageFlags: { [FLAG]: false }, steps: [failed(), tabHidden, succeeded({ [FLAG]: true })] },
            [false, false, true],
        ],
        [
            'a flag sync from another tab keeps the page decision',
            { pageFlags: { [FLAG]: false }, steps: [failed(), noOutcome({ [FLAG]: true })] },
            [false, false],
        ],
        ['nothing known yet is unknown', { pageFlags: { [FLAG]: true }, steps: [] }, [undefined]],
        [
            'a request that failed before mount shows the page decision',
            { pageFlags: { [FLAG]: true }, errorsBeforeMount: ['connection_error'], steps: [noOutcome()] },
            [true],
        ],
        [
            'an error answer before mount shows the page decision',
            { pageFlags: { [FLAG]: true }, errorsBeforeMount: ['api_error_503'], steps: [noOutcome()] },
            [true],
        ],
        [
            'a successful request after an earlier failure before mount shows the flag',
            { pageFlags: { [FLAG]: true }, errorsBeforeMount: [], steps: [noOutcome()] },
            [false],
        ],
        [
            'a successful request with an evaluation error before mount shows the flag',
            {
                pageFlags: { [FLAG]: true },
                errorsBeforeMount: ['errors_while_computing_flags'],
                steps: [noOutcome()],
            },
            [false],
        ],
        [
            'an error record from before mount that is not a list keeps the flag',
            { pageFlags: { [FLAG]: true }, errorsBeforeMount: 'connection_error', steps: [noOutcome()] },
            [false],
        ],
        [
            'a failed load on a page without the identity object keeps the stored flag',
            { pageFlags: 'no page object', steps: [failed({ [FLAG]: true })] },
            [true],
        ],
        [
            'a failed load on a page without flag decisions keeps the stored flag',
            { pageFlags: null, steps: [failed({ [FLAG]: true })] },
            [true],
        ],
        [
            'a failed load on a page that left the switched-off flag out hides the stored flag',
            { pageFlags: { 'other-flag': true }, steps: [failed({ [FLAG]: true })] },
            [false],
        ],
        [
            'a failed load ignores a page value that is not a boolean',
            { pageFlags: { [FLAG]: 'true' }, steps: [failed()] },
            [false],
        ],
    ])('%s', (_name, { pageFlags, errorsBeforeMount, steps }, expected) => {
        if (pageFlags !== 'no page object') {
            window.POSTHOG_USER_IDENTITY_WITH_FLAGS = { distinctID: 'person-1', featureFlags: pageFlags }
        }
        if (errorsBeforeMount !== undefined) {
            window.POSTHOG_GLOBAL_ERRORS = { onFeatureFlagsLoadError: true }
        }
        jest.mocked(posthog.get_property).mockImplementation((key) =>
            key === '$feature_flag_errors' ? errorsBeforeMount : undefined
        )
        initKeaTests()
        const logic = adventCalendarAccessLogic()
        logic.mount()

        const seen = steps.length ? [] : [logic.values.calendarOn]
        for (const step of steps) {
            if (step.outcome === 'tab hidden') {
                setTabHidden(true)
            } else {
                if (step.outcome === 'succeeded') {
                    window.POSTHOG_FEATURE_FLAGS_LOADED = true
                }
                for (const callback of flagCallbacks) {
                    if (step.outcome === 'no outcome') {
                        callback(Object.keys(step.enabledFlags), step.enabledFlags)
                    } else {
                        callback(Object.keys(step.enabledFlags), step.enabledFlags, {
                            errorsLoading: step.outcome === 'failed',
                        })
                    }
                }
            }
            seen.push(logic.values.calendarOn)
        }

        expect(seen).toEqual(expected)
    })
})
