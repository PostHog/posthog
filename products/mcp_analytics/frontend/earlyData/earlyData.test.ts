import { buildActivitySummary } from './activitySummary'

describe('early data derivations', () => {
    it.each([
        // First calls get the celebratory copy, not a stats sentence.
        [
            { lifetimeCalls: 1, totalCalls: 1, distinctClients: 1, errorCalls: 0, topTool: null },
            /first tool call arrived/,
        ],
        [
            { lifetimeCalls: 4, totalCalls: 4, distinctClients: 1, errorCalls: 1, topTool: 'search' },
            /first 4 tool calls arrived/,
        ],
        [
            { lifetimeCalls: 25_000_000, totalCalls: 0, distinctClients: 0, errorCalls: 0, topTool: null },
            /^No tool calls in the last 30 days$/,
        ],
        [
            { lifetimeCalls: null, totalCalls: 0, distinctClients: 0, errorCalls: 0, topTool: null },
            /^No tool calls in the last 30 days$/,
        ],
        [
            { lifetimeCalls: null, totalCalls: 4, distinctClients: 1, errorCalls: 0, topTool: null },
            /^4 tool calls in the last 30 days from 1 client$/,
        ],
        [
            { lifetimeCalls: 3, totalCalls: 4, distinctClients: 1, errorCalls: 0, topTool: null },
            /^Your first 4 tool calls arrived/,
        ],
        // The full sentence composes favorite + failures with correct punctuation.
        [
            { lifetimeCalls: 25_000_000, totalCalls: 42, distinctClients: 3, errorCalls: 4, topTool: 'search_docs' },
            /^42 tool calls in the last 30 days from 3 clients\. search_docs is the favorite\. 4 failures worth a look$/,
        ],
        // Big client and failure counts get thousands separators, unlike the abbreviated call count.
        [
            {
                lifetimeCalls: 25_000_000,
                totalCalls: 21_700_000,
                distinctClients: 1051,
                errorCalls: 533_638,
                topTool: 'execute-sql',
            },
            /^21\.7M tool calls in the last 30 days from 1,051 clients\. execute-sql is the favorite\. 533,638 failures worth a look$/,
        ],
        // Failures read grammatically even without a favorite tool.
        [
            { lifetimeCalls: 42, totalCalls: 42, distinctClients: 0, errorCalls: 1, topTool: null },
            /^42 tool calls in the last 30 days\. 1 failure worth a look$/,
        ],
        [
            { lifetimeCalls: 42, totalCalls: 42, distinctClients: 1, errorCalls: 0, topTool: null },
            /^42 tool calls in the last 30 days from 1 client$/,
        ],
    ])('summarizes %j', (input, expected) => {
        expect(buildActivitySummary(input)).toMatch(expected)
    })
})
