import { appendSnippet, snippetsForField } from './sourceFilterSnippets'

describe('appendSnippet', () => {
    const hasLabel = snippetsForField({ name: 'label_names', type: 'array<string>' })[0]

    test.each([
        ['to an empty expression', '', "has(label_names, '')"],
        [
            'after a finished condition, joined with AND',
            'assignee_id IS NULL',
            "assignee_id IS NULL AND has(label_names, '')",
        ],
        [
            'after an open AND, without a second AND',
            'assignee_id IS NULL AND ',
            "assignee_id IS NULL AND has(label_names, '')",
        ],
        ['inside an open bracket', "(project_name = 'Core' OR", "(project_name = 'Core' OR has(label_names, '')"],
    ])('appends %s and puts the cursor where the value goes', (_, expression, expected) => {
        expect(appendSnippet(expression, hasLabel)).toEqual({
            expression: expected,
            cursor: expected.length - "')".length,
        })
    })
})
