import {
    AccessControlLevel,
    Survey,
    SurveyMatchType,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
    SurveyWidgetType,
} from '~/types'

import {
    SurveyReviewSectionKey,
    SurveyReviewStatus,
    SurveyReviewSummaryPart,
    getSurveyReviewSections,
} from './surveyReview'

const READY_SURVEY: Survey = {
    id: 'survey-id',
    name: 'Draft survey',
    description: '',
    type: SurveyType.Popover,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    questions: [
        { question: 'How likely are you to recommend us?', type: SurveyQuestionType.Open },
        { question: 'What is the main reason for your score?', type: SurveyQuestionType.Open },
    ],
    conditions: {
        url: '/checkout',
        urlMatchType: SurveyMatchType.Contains,
        events: { values: [{ name: 'purchase completed' }] },
        actions: { values: [] },
        seenSurveyWaitPeriodInDays: 14,
    },
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    targeting_flag_filters: undefined,
    appearance: {},
    start_date: null,
    end_date: null,
    archived: false,
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
    user_access_level: AccessControlLevel.Editor,
}

const ALL_READY: Record<SurveyReviewSectionKey, SurveyReviewStatus> = {
    audience: 'ready',
    when: 'ready',
    frequency: 'ready',
    questions: 'ready',
}

// pluralize() joins the count and the noun with a non-breaking space.
const plain = (text: string): string => text.replace(/\u00a0/g, ' ')
const toText = (parts: SurveyReviewSummaryPart[]): string =>
    plain(parts.map((part) => (typeof part === 'string' ? part : part.emphasis)).join(''))

describe('getSurveyReviewSections', () => {
    test.each<{
        name: string
        survey: Partial<Survey>
        statuses: Partial<Record<SurveyReviewSectionKey, SurveyReviewStatus>>
        key: SurveyReviewSectionKey
        summary: string
        warning?: string
    }>([
        {
            name: 'a survey with text, a URL and a trigger is ready',
            survey: {},
            statuses: {},
            key: 'when',
            summary: 'On pages where the URL contains "/checkout", after someone triggers purchase completed.',
        },
        {
            name: 'a question with no text is a warning',
            survey: {
                questions: [
                    { question: 'How likely are you to recommend us?', type: SurveyQuestionType.Open },
                    { question: '  ', type: SurveyQuestionType.Open },
                ],
            },
            statuses: { questions: 'warning' },
            key: 'questions',
            summary: '2 questions in a popover, bottom right.',
            warning: 'Question 2 has no text.',
        },
        {
            name: 'a popover with no URL, event or action condition is a warning',
            survey: { conditions: { events: { values: [] }, actions: { values: [] }, seenSurveyWaitPeriodInDays: 14 } },
            statuses: { when: 'warning' },
            key: 'when',
            summary: 'On any page, as soon as the page loads.',
            warning: 'Shows on every page as soon as it loads. Add a URL or event condition to limit where it appears.',
        },
        {
            name: 'a popup delay on page load says how long after the page loads',
            survey: {
                conditions: { events: { values: [] }, actions: { values: [] } },
                appearance: { surveyPopupDelaySeconds: 5 },
            },
            statuses: { when: 'warning' },
            key: 'when',
            summary: 'On any page, 5 seconds after the page loads.',
            warning:
                'Shows on every page 5 seconds after it loads. Add a URL or event condition to limit where it appears.',
        },
        {
            name: 'a popup delay after a trigger says how long after the trigger',
            survey: { appearance: { surveyPopupDelaySeconds: 1 } },
            statuses: {},
            key: 'when',
            summary: 'On pages where the URL contains "/checkout", 1 second after someone triggers purchase completed.',
        },
        {
            name: 'a survey with no questions is a warning',
            survey: { questions: [] },
            statuses: { questions: 'warning' },
            key: 'questions',
            summary: '0 questions in a popover, bottom right.',
            warning: 'Add at least one question.',
        },
        {
            name: 'a recurring schedule that runs longer than a year is a warning',
            survey: { schedule: SurveySchedule.Recurring, iteration_count: 12, iteration_frequency_days: 365 },
            statuses: { frequency: 'warning' },
            key: 'frequency',
            summary: 'Up to 12 times per person, once every 365 days.',
            warning: 'Runs for 12 years. Lower the number of repeats if you meant less.',
        },
        {
            name: 'no targeting reads as everyone and is not a warning',
            survey: {
                conditions: {
                    url: '/checkout',
                    events: { values: [{ name: 'purchase completed' }] },
                    actions: { values: [] },
                },
            },
            statuses: {},
            key: 'audience',
            summary: 'Everyone. No audience rules are set.',
        },
        {
            name: 'an API survey is shown through code and needs no display conditions',
            survey: { type: SurveyType.API, conditions: null },
            statuses: {},
            key: 'when',
            summary: 'Shown through your own code, wherever you call the surveys API.',
        },
        {
            name: 'a feedback button widget opens on click and is not a warning',
            survey: {
                type: SurveyType.Widget,
                appearance: { widgetType: SurveyWidgetType.Button },
                conditions: { events: { values: [] }, actions: { values: [] } },
            },
            statuses: {},
            key: 'when',
            summary: 'On any page, opened when someone clicks the feedback button.',
        },
        {
            name: 'a selector widget is placed on the element that opens it',
            survey: {
                type: SurveyType.Widget,
                appearance: { widgetType: SurveyWidgetType.Selector, widgetSelector: '#feedback' },
            },
            statuses: {},
            key: 'questions',
            summary: '2 questions when someone clicks #feedback.',
        },
        {
            name: 'excluded device types read as excluded',
            survey: {
                conditions: {
                    url: '/checkout',
                    events: { values: [{ name: 'purchase completed' }] },
                    actions: { values: [] },
                    deviceTypes: ['Mobile'],
                    deviceTypesMatchType: SurveyMatchType.IsNot,
                },
            },
            statuses: {},
            key: 'when',
            summary:
                'On pages where the URL contains "/checkout", not on Mobile, after someone triggers purchase completed.',
        },
        {
            name: 'repeating on every event says so and skips the long-run warning',
            survey: {
                schedule: SurveySchedule.Recurring,
                iteration_count: 12,
                iteration_frequency_days: 365,
                conditions: {
                    events: { values: [{ name: 'purchase completed' }], repeatedActivation: true },
                    actions: { values: [] },
                },
            },
            statuses: {},
            key: 'frequency',
            summary: 'Every time a trigger event fires.',
        },
        {
            name: 'adaptive sampling is a per-interval cap, not a stop',
            survey: {
                response_sampling_limit: 50,
                response_sampling_interval: 1,
                response_sampling_interval_type: 'week',
            },
            statuses: {},
            key: 'frequency',
            summary: 'At most once per person. Collects up to 50 responses per week.',
        },
        {
            name: 'a plain response limit still stops collecting',
            survey: { responses_limit: 100 },
            statuses: {},
            key: 'frequency',
            summary: 'At most once per person. Stops collecting at 100 responses.',
        },
    ])('$name', ({ survey, statuses, key, summary, warning }) => {
        const sections = getSurveyReviewSections({ ...READY_SURVEY, ...survey })

        expect(Object.fromEntries(sections.map((section) => [section.key, section.status]))).toEqual({
            ...ALL_READY,
            ...statuses,
        })
        const section = sections.find((s) => s.key === key)!
        expect(toText(section.summary)).toEqual(summary)
        expect(section.warning && plain(section.warning)).toEqual(warning)
    })
})
