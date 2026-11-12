import { UserBasicType } from '~/types'

import type { ActivityLogEntryApi } from 'products/surveys/frontend/generated/api.schemas'

import { SurveyProvenance, getSurveyProvenance } from './surveyProvenance'

const CREATOR = { id: 1, uuid: 'creator', distinct_id: 'creator', first_name: 'Robin', email: 'robin@example.com' }
const EDITOR = { id: 2, uuid: 'editor', distinct_id: 'editor', first_name: 'Sam', email: 'sam@example.com' }
const SURVEY = { created_by: CREATOR as UserBasicType, created_at: '2026-03-01T09:00:00Z' }

function entry(
    activity: 'created' | 'updated',
    at: string,
    client: string | null,
    { user = CREATOR, intent }: { user?: typeof CREATOR; intent?: string } = {}
): ActivityLogEntryApi {
    return {
        id: `${activity}-${at}`,
        user,
        activity,
        scope: 'Survey',
        item_id: 'survey-id',
        created_at: at,
        is_system: false,
        was_impersonated: false,
        client,
        detail: {
            id: 'survey-id',
            name: 'Draft survey',
            short_id: '',
            type: '',
            ...(intent ? { trigger: { job_type: 'agent', job_id: '', payload: { intent } } } : {}),
        },
    }
}

const FROM_SURVEY = { createdBy: CREATOR, createdAt: SURVEY.created_at, agentIntent: null, lastEdit: null }

describe('getSurveyProvenance', () => {
    // Entries are newest first, as the activity endpoint returns them.
    it.each<[string, ActivityLogEntryApi[] | null, SurveyProvenance]>([
        [
            'created in the app and never edited',
            [entry('created', '2026-03-01T09:00:00Z', null)],
            { ...FROM_SURVEY, channel: 'app' },
        ],
        [
            'created through MCP with an intent',
            [entry('created', '2026-03-01T09:00:00Z', 'mcp', { intent: 'Measure onboarding satisfaction' })],
            { ...FROM_SURVEY, channel: 'mcp', agentIntent: 'Measure onboarding satisfaction' },
        ],
        [
            'edited later through a different channel, newest edit wins',
            [
                entry('updated', '2026-03-03T09:00:00Z', null, { user: EDITOR }),
                entry('updated', '2026-03-02T09:00:00Z', 'mcp'),
                entry('created', '2026-03-01T09:00:00Z', 'mcp'),
            ],
            {
                ...FROM_SURVEY,
                channel: 'mcp',
                lastEdit: { by: EDITOR, at: '2026-03-03T09:00:00Z', channel: 'app' },
            },
        ],
        [
            'intent only on a later edit falls back to the newest entry that has one',
            [
                entry('updated', '2026-03-03T09:00:00Z', 'mcp', { intent: 'Shorten the follow-up question' }),
                entry('updated', '2026-03-02T09:00:00Z', 'mcp', { intent: 'Add a follow-up question' }),
                entry('created', '2026-03-01T09:00:00Z', null),
            ],
            {
                ...FROM_SURVEY,
                channel: 'app',
                agentIntent: 'Shorten the follow-up question',
                lastEdit: { by: CREATOR, at: '2026-03-03T09:00:00Z', channel: 'mcp' },
            },
        ],
        [
            'unknown client string maps to the API',
            [entry('created', '2026-03-01T09:00:00Z', 'zapier')],
            { ...FROM_SURVEY, channel: 'api' },
        ],
        ...['constructor', '__proto__'].map((client): [string, ActivityLogEntryApi[], SurveyProvenance] => [
            `inherited object key "${client}" maps to the API`,
            [entry('created', '2026-03-01T09:00:00Z', client)],
            { ...FROM_SURVEY, channel: 'api' },
        ]),
        [
            'scout client maps to a scout',
            [entry('created', '2026-03-01T09:00:00Z', 'scout:weekly-digest')],
            { ...FROM_SURVEY, channel: 'scout' },
        ],
        ['no activity rows', [], { ...FROM_SURVEY, channel: null }],
        ['activity failed to load', null, { ...FROM_SURVEY, channel: null }],
    ])('%s', (_, entries, expected) => {
        expect(getSurveyProvenance(SURVEY, entries)).toEqual(expected)
    })
})
