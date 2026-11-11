import { AssistantMessage, AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

import { getThinkingMessageFromResponse, getWebSearchResultsByToolUseId } from './thinkingMessages'

function message(thinking: Record<string, unknown>[]): AssistantMessage {
    return { type: AssistantMessageType.Assistant, content: '', meta: { thinking } }
}

function toolUse(id: string): Record<string, unknown> {
    return { type: 'server_tool_use', id, name: 'web_search', input: { query: id } }
}

function toolResult(toolUseId: string, content: unknown): Record<string, unknown> {
    return { type: 'web_search_tool_result', tool_use_id: toolUseId, content }
}

const resultsFor = (name: string): { title: string; url: string }[] => [
    { title: name, url: `https://example.com/${name}` },
]

describe('getThinkingMessageFromResponse', () => {
    let consoleErrorSpy: jest.SpyInstance

    beforeEach(() => {
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        consoleErrorSpy.mockRestore()
    })

    it.each([
        {
            case: 'result in the same message as its tool use',
            messages: [message([toolUse('a'), toolResult('a', resultsFor('a'))])],
            expected: [resultsFor('a')],
        },
        {
            case: 'parallel searches, result in a later message than its tool use',
            messages: [
                message([toolUse('a')]),
                message([toolUse('b'), toolResult('a', resultsFor('a')), toolResult('b', resultsFor('b'))]),
            ],
            expected: [resultsFor('a'), resultsFor('b')],
        },
        {
            case: 'result still streaming',
            messages: [message([toolUse('a'), toolResult('a', undefined)])],
            expected: [undefined],
        },
    ])('attaches web search results for $case', ({ messages, expected }) => {
        const threadResults = getWebSearchResultsByToolUseId(messages)
        for (let render = 0; render < 2; render++) {
            const results = messages
                .flatMap((m) => getThinkingMessageFromResponse(m, threadResults))
                .map((block) => (block.type === 'server_tool_use' ? block.results : null))
            expect(results).toEqual(expected)
        }
        expect(consoleErrorSpy).not.toHaveBeenCalled()
    })
})
