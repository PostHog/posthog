import { ApiError } from 'lib/api-error'
import { urls } from 'scenes/urls'

import type { Breadcrumb } from '~/types'

import type {
    CreateJourneyInputApi,
    JourneyApi,
    JourneySourceEnumApi,
    JourneyStepApi,
    UrlMatchingEnumApi,
} from './generated/api.schemas'
import {
    userJourneysCreateBodyConversionWindowMinutesMax,
    userJourneysCreateBodyNameMax,
    userJourneysCreateBodyStepsItemTwoSelectorMax,
    userJourneysCreateBodyStepsItemTwoTextMax,
    userJourneysCreateBodyStepsItemTwoUrlMax,
    userJourneysCreateBodyStepsMax,
    userJourneysCreateBodyStepsMin,
} from './generated/api.zod'
import { runUrlError } from './journeyRuns'

export const MIN_STEPS = userJourneysCreateBodyStepsMin
export const MAX_STEPS = userJourneysCreateBodyStepsMax
export const MAX_NAME_LENGTH = userJourneysCreateBodyNameMax
export const MAX_URL_LENGTH = userJourneysCreateBodyStepsItemTwoUrlMax
export const MAX_SELECTOR_LENGTH = userJourneysCreateBodyStepsItemTwoSelectorMax
export const MAX_TEXT_LENGTH = userJourneysCreateBodyStepsItemTwoTextMax
export const MAX_CONVERSION_WINDOW_MINUTES = userJourneysCreateBodyConversionWindowMinutesMax
// The generated schema exports no constant for these two, so they mirror
// products/user_journeys/backend/facade/contracts.py by hand.
export const MIN_CONVERSION_WINDOW_MINUTES = 1
export const DEFAULT_CONVERSION_WINDOW_MINUTES = 30

export const URL_MATCHING_OPTIONS: { value: UrlMatchingEnumApi; label: string }[] = [
    { value: 'exact', label: 'URL is' },
    { value: 'contains', label: 'URL contains' },
    { value: 'regex', label: 'URL matches regex' },
]

export function describeUrlMatching(matching: UrlMatchingEnumApi | undefined): string {
    return (URL_MATCHING_OPTIONS.find((option) => option.value === matching) ?? URL_MATCHING_OPTIONS[0]).label
}

export type JourneyLoadError = 'not_found' | 'error'

export function toJourneyLoadError(error: unknown): JourneyLoadError {
    return error instanceof ApiError && error.status === 404 ? 'not_found' : 'error'
}

export function journeysBreadcrumb(): Breadcrumb {
    return { key: 'UserJourneys', name: 'User journeys', path: urls.userJourneys(), iconType: 'insight/paths' }
}

export type JourneyStepType = JourneyStepApi['type']

/** One step as the form edits it. All fields stay on the draft, so switching the type back keeps what was typed. */
export interface JourneyStepDraft {
    /** Stable identity for React keys and reordering. Never sent to the API. */
    key: string
    type: JourneyStepType
    url: string
    url_matching: UrlMatchingEnumApi
    selector: string
    text: string
    href: string
}

export interface JourneyDraft {
    name: string
    description: string
    conversion_window_minutes: number | undefined
    steps: JourneyStepDraft[]
    source: JourneySourceEnumApi
    /** Where a run opens the browser. Empty when the first step names the page. */
    start_url: string
}

/** Errors keyed by field path: `name`, `steps`, or `steps.<index>.<field>` for one field of one step. */
export type JourneyFormErrors = Record<string, string>

export interface JourneyPrefill {
    draft: JourneyDraft
    /** True when the link had steps that could not be read, or more steps than the limit. */
    stepsSkipped: boolean
}

let stepKeyCounter = 0

function nextStepKey(): string {
    stepKeyCounter += 1
    return `step-${stepKeyCounter}`
}

export function emptyStep(type: JourneyStepType = 'pageview'): JourneyStepDraft {
    return { key: nextStepKey(), type, url: '', url_matching: 'exact', selector: '', text: '', href: '' }
}

export function emptyDraft(): JourneyDraft {
    return {
        name: '',
        description: '',
        conversion_window_minutes: DEFAULT_CONVERSION_WINDOW_MINUTES,
        steps: [emptyStep('pageview'), emptyStep('element_click')],
        source: 'manual',
        start_url: '',
    }
}

export function stepToDraft(step: JourneyStepApi): JourneyStepDraft {
    if (step.type === 'pageview') {
        return { ...emptyStep('pageview'), url: step.url, url_matching: step.url_matching ?? 'exact' }
    }
    return {
        ...emptyStep('element_click'),
        selector: step.selector,
        text: step.text ?? '',
        href: step.href ?? '',
        url: step.url ?? '',
        url_matching: step.url_matching ?? 'exact',
    }
}

export function journeyToDraft(journey: JourneyApi): JourneyDraft {
    return {
        name: journey.name,
        description: journey.description,
        conversion_window_minutes: journey.conversion_window_minutes,
        steps: journey.steps.map(stepToDraft),
        source: journey.source,
        start_url: journey.start_url ?? '',
    }
}

export function draftToStep(step: JourneyStepDraft): JourneyStepApi {
    if (step.type === 'pageview') {
        return { type: 'pageview', url: step.url.trim(), url_matching: step.url_matching }
    }
    // The API rejects blank strings for the optional click fields, so a blank field means "match any".
    const orNull = (value: string): string | null => (value.trim() ? value.trim() : null)
    return {
        type: 'element_click',
        selector: step.selector.trim(),
        text: orNull(step.text),
        href: orNull(step.href),
        url: orNull(step.url),
        url_matching: step.url_matching,
    }
}

export function draftToPayload(draft: JourneyDraft): CreateJourneyInputApi {
    return {
        name: draft.name.trim(),
        description: draft.description.trim(),
        conversion_window_minutes: draft.conversion_window_minutes,
        steps: draft.steps.map(draftToStep),
        source: draft.source,
        start_url: draft.start_url.trim() || null,
    }
}

export function moveStep(steps: JourneyStepDraft[], key: string, direction: -1 | 1): JourneyStepDraft[] {
    const from = steps.findIndex((step) => step.key === key)
    const to = from + direction
    if (from === -1 || to < 0 || to >= steps.length) {
        return steps
    }
    const moved = [...steps]
    ;[moved[from], moved[to]] = [moved[to], moved[from]]
    return moved
}

function isValidRegex(pattern: string): boolean {
    try {
        new RegExp(pattern)
        return true
    } catch {
        return false
    }
}

function validateUrl(step: JourneyStepDraft, prefix: string, errors: JourneyFormErrors, required: boolean): void {
    const url = step.url.trim()
    if (!url) {
        if (required) {
            errors[`${prefix}.url`] = 'Enter the page URL.'
        }
        return
    }
    if (url.length > MAX_URL_LENGTH) {
        errors[`${prefix}.url`] = `Use at most ${MAX_URL_LENGTH} characters.`
    } else if (step.url_matching === 'regex' && !isValidRegex(url)) {
        errors[`${prefix}.url`] = 'Enter a valid regular expression.'
    }
}

export function validateDraft(draft: JourneyDraft): JourneyFormErrors {
    const errors: JourneyFormErrors = {}
    const name = draft.name.trim()
    if (!name) {
        errors.name = 'Give the journey a name.'
    } else if (name.length > MAX_NAME_LENGTH) {
        errors.name = `Use at most ${MAX_NAME_LENGTH} characters.`
    }

    const window = draft.conversion_window_minutes
    if (
        window === undefined ||
        !Number.isInteger(window) ||
        window < MIN_CONVERSION_WINDOW_MINUTES ||
        window > MAX_CONVERSION_WINDOW_MINUTES
    ) {
        errors.conversion_window_minutes = `Enter a whole number of minutes from ${MIN_CONVERSION_WINDOW_MINUTES} to ${MAX_CONVERSION_WINDOW_MINUTES}.`
    }

    const startUrl = draft.start_url.trim()
    if (startUrl.length > MAX_URL_LENGTH) {
        errors.start_url = `Use at most ${MAX_URL_LENGTH} characters.`
    } else if (startUrl) {
        const error = runUrlError(startUrl)
        if (error) {
            errors.start_url = error
        }
    }

    if (draft.steps.length < MIN_STEPS) {
        errors.steps = `Add at least ${MIN_STEPS} steps.`
    } else if (draft.steps.length > MAX_STEPS) {
        errors.steps = `Use at most ${MAX_STEPS} steps.`
    }

    draft.steps.forEach((step, index) => {
        const prefix = `steps.${index}`
        if (step.type === 'pageview') {
            validateUrl(step, prefix, errors, true)
            return
        }
        const selector = step.selector.trim()
        if (!selector) {
            errors[`${prefix}.selector`] = 'Enter a CSS selector for the element.'
        } else if (selector.length > MAX_SELECTOR_LENGTH) {
            errors[`${prefix}.selector`] = `Use at most ${MAX_SELECTOR_LENGTH} characters.`
        }
        if (step.text.trim().length > MAX_TEXT_LENGTH) {
            errors[`${prefix}.text`] = `Use at most ${MAX_TEXT_LENGTH} characters.`
        }
        if (step.href.trim().length > MAX_URL_LENGTH) {
            errors[`${prefix}.href`] = `Use at most ${MAX_URL_LENGTH} characters.`
        }
        validateUrl(step, prefix, errors, false)
    })
    return errors
}

/**
 * Turns the `attr` of an API validation error into a form error key. The API joins nested field names with `__`,
 * so `steps__1__selector` is the selector of the second step.
 */
export function serverErrorKey(attr: string | null | undefined): string | null {
    if (!attr) {
        return null
    }
    const parts = attr.split('__')
    if (parts[0] === 'steps') {
        if (parts.length >= 3 && /^\d+$/.test(parts[1])) {
            return `steps.${parts[1]}.${parts[2]}`
        }
        return 'steps'
    }
    return ['name', 'description', 'conversion_window_minutes', 'start_url'].includes(parts[0]) ? parts[0] : null
}

function asString(value: unknown): string | null {
    if (typeof value === 'string') {
        return value
    }
    // kea-router parses search params that look like numbers or booleans, so a name like "404" arrives as a number.
    if ((typeof value === 'number' && Number.isFinite(value)) || typeof value === 'boolean') {
        return String(value)
    }
    return null
}

function optionalString(record: Record<string, unknown>, field: string): string | undefined {
    const value = record[field]
    if (value === undefined || value === null) {
        return ''
    }
    return typeof value === 'string' ? value : undefined
}

function parseUrlMatching(value: unknown): UrlMatchingEnumApi | undefined {
    if (value === undefined || value === null) {
        return 'exact'
    }
    return URL_MATCHING_OPTIONS.find((option) => option.value === value)?.value
}

function parsePrefillStep(raw: unknown): JourneyStepDraft | null {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
        return null
    }
    const record = raw as Record<string, unknown>
    const urlMatching = parseUrlMatching(record.url_matching)
    const url = optionalString(record, 'url')
    if (urlMatching === undefined || url === undefined) {
        return null
    }
    if (record.type === 'pageview') {
        return url ? { ...emptyStep('pageview'), url, url_matching: urlMatching } : null
    }
    if (record.type === 'element_click') {
        const text = optionalString(record, 'text')
        const href = optionalString(record, 'href')
        if (typeof record.selector !== 'string' || !record.selector || text === undefined || href === undefined) {
            return null
        }
        return { ...emptyStep('element_click'), selector: record.selector, text, href, url, url_matching: urlMatching }
    }
    return null
}

function parseStepsParam(value: unknown): unknown[] | null {
    if (Array.isArray(value)) {
        return value
    }
    if (typeof value !== 'string') {
        return null
    }
    try {
        const parsed: unknown = JSON.parse(value)
        return Array.isArray(parsed) ? parsed : null
    } catch {
        return null
    }
}

/**
 * Reads the create form's prefill from the URL's search params. The link comes from outside the app, so anything
 * that is not a well-formed value is left out rather than trusted. See `urls.userJourneyNew` for the params.
 */
export function parseJourneyPrefill(searchParams: Record<string, unknown>): JourneyPrefill | null {
    const name = asString(searchParams.name)
    const description = asString(searchParams.description)
    const rawSteps = searchParams.steps === undefined ? null : parseStepsParam(searchParams.steps)
    if (name === null && description === null && searchParams.steps === undefined) {
        return null
    }

    const draft = emptyDraft()
    let stepsSkipped = searchParams.steps !== undefined && rawSteps === null
    if (rawSteps !== null) {
        const readable = rawSteps.map(parsePrefillStep).filter((step): step is JourneyStepDraft => step !== null)
        stepsSkipped = readable.length < rawSteps.length || readable.length > MAX_STEPS
        if (readable.length > 0) {
            draft.steps = readable.slice(0, MAX_STEPS)
        }
    }

    return {
        draft: {
            ...draft,
            name: name?.slice(0, MAX_NAME_LENGTH) ?? '',
            description: description ?? '',
            source: searchParams.source === 'toolbar' ? 'toolbar' : 'manual',
        },
        stepsSkipped,
    }
}
