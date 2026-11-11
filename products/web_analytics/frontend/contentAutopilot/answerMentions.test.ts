import { AnswerBrand, answerMentions } from './answerMentions'

const OWN: AnswerBrand = { key: 'own', name: 'Example', domain: null, isOwn: true, terms: ['Example', 'Example Cloud'] }
const RIVAL: AnswerBrand = {
    key: 'rival.example.org',
    name: 'Rival',
    domain: 'rival.example.org',
    isOwn: false,
    terms: ['Rival', 'rival.example.org'],
}

describe('answerMentions', () => {
    it.each([
        [
            'splits the text into brand names and lists brands in the order the answer names them',
            'Rival is fine, but Example Cloud and example win.',
            [],
            [
                ['Rival', 'rival.example.org'],
                [' is fine, but ', null],
                ['Example Cloud', 'own'],
                [' and ', null],
                ['example', 'own'],
                [' win.', null],
            ],
            [
                ['rival.example.org', 1, false],
                ['own', 2, true],
            ],
        ],
        [
            'ignores a brand name inside another word and counts a cited subdomain',
            'Examples abound. See docs.rival.example.org.',
            ['https://docs.rival.example.org/guide'],
            [
                ['Examples abound. See docs.', null],
                ['rival.example.org', 'rival.example.org'],
                ['.', null],
            ],
            [['rival.example.org', 1, true]],
        ],
    ] as const)('%s', (_, text, citedUrls, segments, mentions) => {
        const result = answerMentions(text, [OWN, RIVAL], [...citedUrls], true)

        expect(result.segments.map(({ text, brandKey }) => [text, brandKey])).toEqual(segments)
        expect(result.mentions.map(({ brand, count, cited }) => [brand.key, count, cited])).toEqual(mentions)
    })
})
