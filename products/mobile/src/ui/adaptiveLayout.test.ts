import { adaptiveLayout } from './adaptiveLayout'

test.each([
    { width: 402, height: 874, left: 0, right: 0, rail: false, paired: false, side: 'right' },
    { width: 951, height: 669, left: 0, right: 70, rail: true, paired: true, side: 'right' },
    { width: 951, height: 669, left: 70, right: 0, rail: true, paired: true, side: 'left' },
    { width: 820, height: 669, left: 44, right: 44, rail: true, paired: false, side: 'right' },
    { width: 669, height: 951, left: 0, right: 0, rail: false, paired: false, side: 'right' },
    { width: 466, height: 678, left: 0, right: 70, rail: true, paired: false, side: 'right' },
])(
    'fits content after both safe edges and navigation ($width × $height, $left/$right)',
    ({ width, height, left, right, rail, paired, side }) => {
        const result = adaptiveLayout(width, height, left, right)
        expect(result).toMatchObject({ rail, paired, railSide: side })
        expect(result.contentWidth).toBe(width - left - right - (rail ? 80 : 0))
    }
)
