import type { DecisionAnswerInput } from '@/model/types'

import {
    type AnswerPlan,
    decisionQuestionFor,
    parsePermissionRequest,
    planAnswer,
    requestKind,
} from './permissionRequest'
import type { PendingRequest } from './types'

function pending(frame: Record<string, unknown>): PendingRequest {
    const record = parsePermissionRequest(frame)
    if (!record) {
        throw new Error('fixture did not parse')
    }
    return { record, kind: requestKind(record), replayed: false }
}

const WHICH_FIX = { question: 'Which fix?', options: [{ label: 'SDK' }, { label: 'Server' }] }
const ADD_TEST = { question: 'Add a test?', options: [{ label: 'Yes' }, { label: 'No' }] }

function questionRequest(questions: unknown[]): PendingRequest {
    return pending({
        requestId: 'q',
        options: [
            { optionId: 'option_0', kind: 'allow_once', name: 'SDK' },
            { optionId: 'option_1', kind: 'allow_once', name: 'Server' },
        ],
        toolCall: { toolCallId: 'tc', _meta: { codeToolKind: 'question', questions } },
    })
}

const ONE_QUESTION = questionRequest([WHICH_FIX])
const TWO_QUESTIONS = questionRequest([WHICH_FIX, ADD_TEST])

const EDIT = pending({
    requestId: 'p',
    options: [
        { optionId: 'allow', kind: 'allow_once', name: 'Yes' },
        { optionId: 'reject', kind: 'reject_once', name: 'No' },
        { optionId: 'feedback', kind: 'reject_once', name: 'No, and say why', _meta: { customInput: true } },
    ],
    toolCall: { toolCallId: 'tc', title: 'Edit src/a.ts', _meta: { claudeCode: { toolName: 'Edit' } } },
})

const PLAN = pending({
    requestId: 'plan',
    options: [
        { optionId: 'bypassPermissions', kind: 'allow_always', name: 'Yes, and bypass permissions' },
        { optionId: 'auto', kind: 'allow_always', name: 'Yes, and use "auto" mode' },
        { optionId: 'plan', kind: 'allow_always', name: 'Stay in plan mode' },
        { optionId: 'reject_with_feedback', kind: 'reject_once', name: 'No', _meta: { customInput: true } },
    ],
    toolCall: { toolCallId: 'tc', kind: 'switch_mode', rawInput: { plan: '# Plan', toolName: 'ExitPlanMode' } },
})

const pick = (questionId: string, optionId: string, text: string): DecisionAnswerInput => ({
    questionId,
    optionId,
    text,
})
const typed = (questionId: string, text: string): DecisionAnswerInput => ({ questionId, text })

describe('permissionRequest', () => {
    test('keeps the exact request details independently of later frame changes', () => {
        const toolCall = {
            toolCallId: 'example-call',
            rawInput: {
                toolName: 'mcp__example__write',
                arguments: { path: '/example/report.txt', content: '<plain text>' },
            },
            content: [{ type: 'text', text: 'Example request' }],
            locations: [{ path: '/example/report.txt' }],
        }
        const request = pending({
            requestId: 'example-request',
            options: [{ optionId: 'allow', kind: 'allow_once', name: 'Allow' }],
            toolCall,
        })
        const details = JSON.stringify(toolCall, null, 2)
        toolCall.rawInput.arguments.content = 'changed after parsing'
        expect(decisionQuestionFor(request, []).details).toBe(details)
    })

    test.each<[string, PendingRequest, string[], DecisionAnswerInput, AnswerPlan]>([
        [
            'a picked option answers by question text',
            ONE_QUESTION,
            [],
            pick('q', 'option_1', 'Server'),
            { type: 'respond', params: { requestId: 'q', optionId: 'option_1', answers: { 'Which fix?': 'Server' } } },
        ],
        [
            'a typed answer goes out with option_0 and the text as custom input',
            ONE_QUESTION,
            [],
            typed('q', 'Both'),
            {
                type: 'respond',
                params: {
                    requestId: 'q',
                    optionId: 'option_0',
                    answers: { 'Which fix?': 'Both' },
                    customInput: 'Both',
                },
            },
        ],
        [
            'the first of two questions stays on the device',
            TWO_QUESTIONS,
            [],
            pick('q', 'option_1', 'Server'),
            { type: 'next_question', label: 'Server' },
        ],
        [
            'the last of two questions sends both answers',
            TWO_QUESTIONS,
            ['Server'],
            pick('q#1', 'option_0', 'Yes'),
            {
                type: 'respond',
                params: {
                    requestId: 'q',
                    optionId: 'option_1',
                    answers: { 'Which fix?': 'Server', 'Add a test?': 'Yes' },
                },
            },
        ],
        [
            'a picked permission option is sent as is',
            EDIT,
            [],
            pick('p', 'reject', 'No'),
            { type: 'respond', params: { requestId: 'p', optionId: 'reject' } },
        ],
        [
            'a typed reply to a permission goes with the option that takes text, never an allow',
            EDIT,
            [],
            typed('p', 'Edit b.ts instead'),
            { type: 'respond', params: { requestId: 'p', optionId: 'feedback', customInput: 'Edit b.ts instead' } },
        ],
        [
            'a typed reply to a plan rejects it with feedback',
            PLAN,
            [],
            typed('plan', 'Keep the API as is'),
            {
                type: 'respond',
                params: { requestId: 'plan', optionId: 'reject_with_feedback', customInput: 'Keep the API as is' },
            },
        ],
    ])('planAnswer: %s', (_name, request, answered, input, expected) => {
        expect(planAnswer(request, answered, input)).toEqual(expected)
    })

    test.each<[string, PendingRequest, string[], { id: string; question: string; optionIds: string[] }]>([
        [
            'a plan offers the two approval modes, Auto first',
            PLAN,
            [],
            { id: 'plan', question: 'Approve the plan?', optionIds: ['auto', 'bypassPermissions'] },
        ],
        [
            'a permission names the tool',
            EDIT,
            [],
            { id: 'p', question: 'Allow Edit src/a.ts?', optionIds: ['allow', 'reject', 'feedback'] },
        ],
        [
            'the second question gets its own card id',
            TWO_QUESTIONS,
            ['Server'],
            { id: 'q#1', question: 'Add a test?', optionIds: ['option_0', 'option_1'] },
        ],
    ])('decisionQuestionFor: %s', (_name, request, answered, expected) => {
        const question = decisionQuestionFor(request, answered)
        expect({
            id: question.id,
            question: question.question,
            optionIds: question.options.map((option) => option.id),
        }).toEqual(expected)
    })
})
