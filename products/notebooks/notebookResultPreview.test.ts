import { notebookResultPreview } from './notebookResultPreview'

describe('notebookResultPreview', () => {
    it.each([
        ['keeps a short value', '3', '3'],
        ['clips a long value', 'x'.repeat(5000), 'x'.repeat(2048)],
        ['omits an empty value', '', undefined],
    ])('%s', (_, resultText, expected) => {
        expect(notebookResultPreview({ result_text: resultText }).result_text).toEqual(expected)
    })
})
