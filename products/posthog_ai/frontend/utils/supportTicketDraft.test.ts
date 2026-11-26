import type { ThreadItem } from '../types/streamTypes'
import { extractSupportTicketDraft, findSupportTicketDraft } from './supportTicketDraft'

const TICKET = [
    '**What I want:** The checkout-v2 flag shows the control variant to every user.',
    '**Questions:**',
    '- Why does the flag ignore the 50% rollout?',
    '**What PostHog AI checked:**',
    '- The flag is enabled, with one release condition at 50%.',
    '**Left for support:** Why every evaluation returns control.',
    '**Error:**',
    '```\nFlagEvaluationError: no variant\n\n  at evaluate (flags.ts:12)\n```',
].join('\n\n')

const agentMessage = (text: string, id = text): ThreadItem => ({ id, type: 'assistant_message', text, complete: true })

describe('supportTicketDraft', () => {
    test.each<[string, string, string | null]>([
        [
            'a ticket between the agent intro and hand-off',
            `Here is a ticket you can send.\n\n${TICKET}\n\nType /ticket to open the support form. I could not resolve:\n\n- the replay link`,
            TICKET,
        ],
        [
            'a ticket in a fenced block',
            `Here it is:\n\n\`\`\`\`markdown\n${TICKET}\n\`\`\`\`\n\nNothing is sent until you send it.`,
            TICKET,
        ],
        [
            'a label alone on its line, with a plain paragraph as its body',
            '**What I want:** Help with my flag.\n\n**Error:**\n\nTypeError: x is undefined\n\nNothing is sent until you send it.',
            '**What I want:** Help with my flag.\n\n**Error:**\n\nTypeError: x is undefined',
        ],
        [
            'a message that only names the first part',
            'Want me to write a ticket? It starts with **What I want:** and your question.',
            null,
        ],
    ])('extracts %s', (_name, message, expected) => {
        expect(extractSupportTicketDraft(message)).toEqual(expected)
    })

    test.each<[string, ThreadItem[], string | null]>([
        [
            'the latest ticket, past a later message without one',
            [
                agentMessage('**What I want:** An older question.'),
                { id: 'h1', type: 'human_message', text: 'Add the error too' },
                agentMessage(TICKET),
                agentMessage('Type /ticket when you are ready.'),
            ],
            TICKET,
        ],
        [
            'no ticket from before the conversation was cleared',
            [agentMessage(TICKET), { id: 'c1', type: 'conversation_cleared' }, agentMessage('Hi again.')],
            null,
        ],
    ])('finds %s', (_name, threadItems, expected) => {
        expect(findSupportTicketDraft(threadItems)).toEqual(expected)
    })
})
