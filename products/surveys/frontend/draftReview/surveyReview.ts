import { pluralize } from 'lib/utils/strings'
import { NewSurvey } from 'scenes/surveys/constants'
import { positionDisplayNames } from 'scenes/surveys/survey-appearance/SurveyAppearanceSections'
import {
    doesSurveyRepeatOnEveryEvent,
    getRecurringSurveyScheduleInfo,
    getSurveyAudienceRolloutPercentage,
    getSurveyAudienceRuleCount,
    getSurveyCollectionLimitSummary,
    getSurveyTargetingFilters,
    isSimpleSurveyAudienceTargeting,
} from 'scenes/surveys/utils'

import { Survey, SurveyMatchType, SurveyPosition, SurveySchedule, SurveyType, SurveyWidgetType } from '~/types'

export type SurveyReviewSectionKey = 'audience' | 'when' | 'frequency' | 'questions'
export type SurveyReviewStatus = 'ready' | 'warning'
export type SurveyPreviewArea = 'page' | 'survey'

/** A plain string renders as text; `{ emphasis }` renders as a key value the reader should notice. */
export type SurveyReviewSummaryPart = string | { emphasis: string }

export interface SurveyReviewSection {
    key: SurveyReviewSectionKey
    title: string
    status: SurveyReviewStatus
    summary: SurveyReviewSummaryPart[]
    warning?: string
    previewArea: SurveyPreviewArea | null
}

type ReviewedSurvey = Survey | NewSurvey

/** How a survey reaches people. Only in-app surveys render on the customer's own pages. */
export type SurveyDelivery = 'in_app' | 'api' | 'hosted'

const DELIVERY_BY_TYPE: Record<SurveyType, SurveyDelivery> = {
    [SurveyType.Popover]: 'in_app',
    [SurveyType.Widget]: 'in_app',
    [SurveyType.FullScreen]: 'in_app',
    [SurveyType.API]: 'api',
    [SurveyType.ExternalSurvey]: 'hosted',
}

export function getSurveyDelivery(survey: Pick<ReviewedSurvey, 'type'>): SurveyDelivery {
    return DELIVERY_BY_TYPE[survey.type]
}

const URL_MATCH_LABELS: Record<SurveyMatchType, string> = {
    [SurveyMatchType.Exact]: 'is',
    [SurveyMatchType.IsNot]: 'is not',
    [SurveyMatchType.Contains]: 'contains',
    [SurveyMatchType.NotIContains]: 'does not contain',
    [SurveyMatchType.Regex]: 'matches',
    [SurveyMatchType.NotRegex]: 'does not match',
}

const NEGATING_MATCH_TYPES: SurveyMatchType[] = [
    SurveyMatchType.IsNot,
    SurveyMatchType.NotIContains,
    SurveyMatchType.NotRegex,
]

const DAYS_PER_YEAR = 365

const em = (emphasis: string): SurveyReviewSummaryPart => ({ emphasis })

function formatRunLength(days: number): string {
    const years = Math.floor(days / DAYS_PER_YEAR)
    if (days % DAYS_PER_YEAR === 0) {
        return pluralize(years, 'year')
    }
    return years < 2 ? 'more than a year' : `over ${pluralize(years, 'year')}`
}

function formatInterval(count: number, unit: string | null | undefined): string {
    return count === 1 ? `${unit}` : pluralize(count, `${unit}`)
}

interface SectionContent {
    summary: SurveyReviewSummaryPart[]
    warning?: string
}

interface SectionDefinition {
    key: SurveyReviewSectionKey
    title: string
    previewArea: SurveyPreviewArea | null
    build: (survey: ReviewedSurvey) => SectionContent
}

function joinClauses(clauses: SurveyReviewSummaryPart[][]): SurveyReviewSummaryPart[] {
    return clauses.flatMap((clause, i) => {
        if (i === 0) {
            return clause
        }
        return [i === clauses.length - 1 ? ', and ' : ', ', ...clause]
    })
}

function getLinkedFlagClauses(survey: ReviewedSurvey): SurveyReviewSummaryPart[][] {
    const clauses: SurveyReviewSummaryPart[][] = []
    if (survey.linked_flag?.key) {
        clauses.push(['with ', em(survey.linked_flag.key), ' on'])
    } else if (survey.linked_flag_id) {
        clauses.push(['with ', em('a linked feature flag'), ' on'])
    }
    if ((survey.linked_flag || survey.linked_flag_id) && survey.conditions?.linkedFlagVariant) {
        clauses.push(['on the ', em(survey.conditions.linkedFlagVariant), ' variant'])
    }
    return clauses
}

function getTargetingClauses(survey: ReviewedSurvey): SurveyReviewSummaryPart[][] {
    const clauses: SurveyReviewSummaryPart[][] = []
    const filters = getSurveyTargetingFilters(survey)
    const ruleCount = getSurveyAudienceRuleCount(filters)
    const rolloutPercentage = getSurveyAudienceRolloutPercentage(filters)
    if (!isSimpleSurveyAudienceTargeting(filters)) {
        clauses.push(['who match ', em('advanced targeting rules')])
    } else if (ruleCount > 0) {
        clauses.push(['who match ', em(pluralize(ruleCount, 'audience rule'))])
    }
    if (rolloutPercentage !== null && rolloutPercentage < 100) {
        clauses.push(['sampled at ', em(`${rolloutPercentage}%`)])
    }
    return clauses
}

function buildAudience(survey: ReviewedSurvey): SectionContent {
    if (getSurveyDelivery(survey) === 'hosted') {
        return { summary: [em('Anyone with the link'), '.'] }
    }

    const clauses = [...getTargetingClauses(survey), ...getLinkedFlagClauses(survey)]
    if (survey.conditions?.seenSurveyWaitPeriodInDays) {
        clauses.push([
            'who have not seen a survey in the last ',
            em(pluralize(survey.conditions.seenSurveyWaitPeriodInDays, 'day')),
        ])
    }

    if (clauses.length === 0) {
        return { summary: [em('Everyone'), '. No audience rules are set.'] }
    }
    return { summary: ['People ', ...joinClauses(clauses), '.'] }
}

/** Widgets never open on their own. The visitor opens them from the feedback button or a selector. */
function getWidgetOpener(survey: ReviewedSurvey): SurveyReviewSummaryPart[] | null {
    if (survey.type !== SurveyType.Widget) {
        return null
    }
    return survey.appearance?.widgetType === SurveyWidgetType.Selector
        ? [em(survey.appearance.widgetSelector || 'the selector element')]
        : [em('the feedback button')]
}

type SurveyConditions = NonNullable<ReviewedSurvey['conditions']>

function describePageScope(conditions: SurveyConditions | null | undefined): SurveyReviewSummaryPart[] {
    const scope: SurveyReviewSummaryPart[] = conditions?.url
        ? [
              'On pages where the URL ',
              em(`${URL_MATCH_LABELS[conditions.urlMatchType ?? SurveyMatchType.Contains]} "${conditions.url}"`),
          ]
        : ['On ', em('any page')]
    if (conditions?.selector) {
        scope.push(' that have ', em(conditions.selector))
    }
    return scope
}

function describeDevices(conditions: SurveyConditions | null | undefined): SurveyReviewSummaryPart[] {
    if (!conditions?.deviceTypes?.length) {
        return []
    }
    const excluded = NEGATING_MATCH_TYPES.includes(conditions.deviceTypesMatchType as SurveyMatchType)
    return [excluded ? ', not on ' : ', on ', em(conditions.deviceTypes.join(' or '))]
}

/** The SDK holds a survey back for the popup delay after it is due, whether it is due on load or on a trigger. */
function describeTiming(
    widgetOpener: SurveyReviewSummaryPart[] | null,
    triggers: string[],
    delaySeconds: number
): SurveyReviewSummaryPart[] {
    if (widgetOpener) {
        return [', opened when someone clicks ', ...widgetOpener]
    }
    const delay: SurveyReviewSummaryPart[] =
        delaySeconds > 0 ? [', ', em(pluralize(delaySeconds, 'second')), ' after'] : [', after']
    if (triggers.length > 0) {
        return [...delay, ' someone triggers ', em(triggers.join(' or '))]
    }
    return delaySeconds > 0 ? [...delay, ' the page loads'] : [', as soon as the page loads']
}

function buildWhen(survey: ReviewedSurvey): SectionContent {
    const delivery = getSurveyDelivery(survey)
    if (delivery === 'api') {
        return { summary: ['Shown ', em('through your own code'), ', wherever you call the surveys API.'] }
    }
    if (delivery === 'hosted') {
        return { summary: ['Shown on a hosted page ', em('through the survey link'), '.'] }
    }

    const conditions = survey.conditions
    const triggers = [...(conditions?.events?.values ?? []), ...(conditions?.actions?.values ?? [])]
        .map((trigger) => trigger.name)
        .filter((name): name is string => !!name)
    const widgetOpener = getWidgetOpener(survey)
    const delaySeconds = survey.appearance?.surveyPopupDelaySeconds ?? 0

    const showsEverywhere = !widgetOpener && !conditions?.url && !conditions?.selector && triggers.length === 0
    return {
        summary: [
            ...describePageScope(conditions),
            ...describeDevices(conditions),
            ...describeTiming(widgetOpener, triggers, delaySeconds),
            '.',
        ],
        warning: showsEverywhere ? getShowsEverywhereWarning(delaySeconds) : undefined,
    }
}

function getShowsEverywhereWarning(delaySeconds: number): string {
    const timing = delaySeconds > 0 ? `${pluralize(delaySeconds, 'second')} after it loads` : 'as soon as it loads'
    return `Shows on every page ${timing}. Add a URL or event condition to limit where it appears.`
}

function describeRepeats(survey: ReviewedSurvey): SurveyReviewSummaryPart[] {
    if (doesSurveyRepeatOnEveryEvent(survey)) {
        return [em('Every time'), ' a trigger event fires.']
    }
    if (survey.schedule === SurveySchedule.Recurring && survey.iteration_count && survey.iteration_frequency_days) {
        return [
            'Up to ',
            em(pluralize(survey.iteration_count, 'time')),
            ' per person, ',
            em(`once every ${pluralize(survey.iteration_frequency_days, 'day')}`),
            '.',
        ]
    }
    if (survey.schedule === SurveySchedule.Always) {
        return [em('Every time'), ' the conditions match.']
    }
    return ['At most ', em('once'), ' per person.']
}

function describeLimit(survey: ReviewedSurvey, delivery: SurveyDelivery): SurveyReviewSummaryPart[] {
    const limit = getSurveyCollectionLimitSummary(survey)
    if (!limit) {
        return delivery === 'hosted' ? [em('No limit'), ' on responses.'] : []
    }
    if (limit.label === 'Response limit') {
        return ['Stops collecting at ', em(limit.value), ' responses.']
    }
    return [
        'Collects up to ',
        em(pluralize(survey.response_sampling_limit ?? 0, 'response')),
        ' per ',
        em(formatInterval(survey.response_sampling_interval ?? 0, survey.response_sampling_interval_type)),
        '.',
    ]
}

function getRunLengthWarning(survey: ReviewedSurvey): string | undefined {
    const schedule = doesSurveyRepeatOnEveryEvent(survey) ? null : getRecurringSurveyScheduleInfo(survey)
    return schedule && schedule.totalDurationDays > DAYS_PER_YEAR
        ? `Runs for ${formatRunLength(schedule.totalDurationDays)}. Lower the number of repeats if you meant less.`
        : undefined
}

function buildFrequency(survey: ReviewedSurvey): SectionContent {
    const delivery = getSurveyDelivery(survey)
    const repeats = delivery === 'hosted' ? [] : describeRepeats(survey)
    const limit = describeLimit(survey, delivery)
    return {
        summary: [...repeats, ...(repeats.length && limit.length ? [' '] : []), ...limit],
        warning: getRunLengthWarning(survey),
    }
}

const QUESTION_PLACEMENT: Record<SurveyType, (survey: ReviewedSurvey) => SurveyReviewSummaryPart[]> = {
    [SurveyType.Popover]: (survey) => [
        ' in ',
        em('a popover'),
        ', ',
        em(positionDisplayNames[survey.appearance?.position ?? SurveyPosition.Right].toLowerCase()),
        '.',
    ],
    [SurveyType.Widget]: (survey) =>
        survey.appearance?.widgetType === SurveyWidgetType.Selector
            ? [' when someone clicks ', em(survey.appearance.widgetSelector || 'the selector element'), '.']
            : [' in ', em('a feedback button'), '.'],
    [SurveyType.FullScreen]: () => [' in ', em('full screen'), '.'],
    [SurveyType.API]: () => [', rendered by your code.'],
    [SurveyType.ExternalSurvey]: () => [' on a hosted page.'],
}

function getQuestionsWarning(survey: ReviewedSurvey): string | undefined {
    if (survey.questions.length === 0) {
        return 'Add at least one question.'
    }
    const untitled = survey.questions.flatMap((question, index) => (question.question?.trim() ? [] : [index + 1]))
    return untitled.length > 0
        ? `${pluralize(untitled.length, 'Question', 'Questions', false)} ${untitled.join(', ')} ${untitled.length === 1 ? 'has' : 'have'} no text.`
        : undefined
}

function buildQuestions(survey: ReviewedSurvey): SectionContent {
    return {
        summary: [em(pluralize(survey.questions.length, 'question')), ...QUESTION_PLACEMENT[survey.type](survey)],
        warning: getQuestionsWarning(survey),
    }
}

const SECTIONS: SectionDefinition[] = [
    {
        key: 'audience',
        title: 'Who sees it',
        previewArea: null,
        build: buildAudience,
    },
    {
        key: 'when',
        title: 'Where and when',
        previewArea: 'page',
        build: buildWhen,
    },
    {
        key: 'frequency',
        title: 'How often',
        previewArea: null,
        build: buildFrequency,
    },
    {
        key: 'questions',
        title: 'What they see',
        previewArea: 'survey',
        build: buildQuestions,
    },
]

export function getSurveyReviewSections(survey: ReviewedSurvey): SurveyReviewSection[] {
    return SECTIONS.map(({ build, ...definition }) => {
        const { summary, warning } = build(survey)
        return { ...definition, summary, status: warning ? 'warning' : 'ready', warning }
    })
}
