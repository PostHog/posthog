import type { AnswerSegment } from './answerMentions'
import { answerSentimentBlocks } from './answerSentiment'

const sentence = (start: number, end: number, label = 'positive'): any => ({ start, end, label, score: 0.9 })
const plain = (text: string): AnswerSegment[] => [{ text, brandKey: null }]

describe('answerSentimentBlocks', () => {
    it.each([
        [
            'keeps the answer as one block when no sentence is scored',
            'Example is fast.',
            plain('Example is fast.'),
            [],
            [[null, [['Example is fast.', null]]]],
        ],
        [
            'cuts a brand name out of its sentence without splitting the sentence',
            'Rival is slow. Example is fast. Done.',
            [
                { text: 'Rival is slow. ', brandKey: null },
                { text: 'Example', brandKey: 'own' },
                { text: ' is fast. Done.', brandKey: null },
            ],
            [sentence(15, 31)],
            [
                [null, [['Rival is slow. ', null]]],
                [
                    'positive',
                    [
                        ['Example', 'own'],
                        [' is fast.', null],
                    ],
                ],
                [null, [[' Done.', null]]],
            ],
        ],
        [
            'reads offsets as code points, so an emoji before the sentence does not shift it',
            '\u{1F680} Go. Example wins.',
            plain('\u{1F680} Go. Example wins.'),
            [sentence(6, 19, 'negative')],
            [
                [null, [['\u{1F680} Go. ', null]]],
                ['negative', [['Example wins.', null]]],
            ],
        ],
        [
            'leaves out a sentence that overlaps the one before it or lies past the end of the text',
            'Example is fast. So good.',
            plain('Example is fast. So good.'),
            [sentence(0, 16), sentence(10, 25, 'negative'), sentence(40, 50, 'negative')],
            [
                ['positive', [['Example is fast.', null]]],
                [null, [[' So good.', null]]],
            ],
        ],
    ])('%s', (_name, text, segments, sentences, expected) => {
        const blocks = answerSentimentBlocks(text, segments, sentences)
        expect(
            blocks.map((block) => [
                block.sentence?.label ?? null,
                block.segments.map((segment) => [segment.text, segment.brandKey]),
            ])
        ).toEqual(expected)
        expect(blocks.flatMap((block) => block.segments.map((segment) => segment.text)).join('')).toBe(text)
    })
})
