import { adaptiveLayout } from './adaptiveLayout'

test.each([
    { width: 951, height: 669, left: 0, right: 84, rail: true, paired: true, side: 'right' },
    { width: 951, height: 669, left: 84, right: 0, rail: true, paired: true, side: 'left' },
    { width: 469, height: 669, left: 84, right: 0, rail: false, paired: false, side: 'left' },
    { width: 402, height: 874, left: 0, right: 0, rail: false, paired: false, side: 'right' },
    { width: 951, height: 669, left: 0, right: 70, rail: true, paired: true, side: 'right' },
    { width: 951, height: 669, left: 70, right: 0, rail: true, paired: true, side: 'left' },
    { width: 820, height: 669, left: 44, right: 44, rail: true, paired: false, side: 'right' },
    { width: 669, height: 951, left: 0, right: 0, rail: false, paired: false, side: 'right' },
    { width: 466, height: 678, left: 0, right: 70, rail: false, paired: false, side: 'right' },
    { width: 874, height: 402, left: 62, right: 62, rail: false, paired: false, side: 'right' },
    { width: 923, height: 411, left: 24, right: 0, rail: false, paired: false, side: 'left' },
])(
    'fits content after both safe edges and navigation ($width × $height, $left/$right)',
    ({ width, height, left, right, rail, paired, side }) => {
        const result = adaptiveLayout(width, height, left, right)
        expect(result).toMatchObject({ rail, paired, railSide: side })
        expect(result.contentWidth).toBe(width - left - right - (rail ? 80 : 0))
    }
)

test.each([
    { width: 951, height: 669, navigation: true },
    { width: 669, height: 951, navigation: true },
    { width: 874, height: 402, navigation: false },
    { width: 923, height: 411, navigation: false },
])('preserves report reading space at $width × $height', ({ width, height, navigation }) => {
    expect(adaptiveLayout(width, height, 0, 0).reportNavigation).toBe(navigation)
})

test.each([0, 84])('uses native navigation without a second rail when the leading inset is %s', (left) => {
    expect(adaptiveLayout(951, 669, left, 84 - left, [], true)).toMatchObject({
        rail: false,
        contentWidth: 867,
        paired: true,
        reportNavigation: false,
    })
})

test.each([
    { frame: { x: 440, y: 0, width: 20, height: 669 }, width: 951, height: 669, axis: 'row', extent: 440 },
    { frame: { x: 0, y: 440, width: 669, height: 20 }, width: 669, height: 951, axis: 'column', extent: 440 },
])('aligns both panes to an active fold ($axis)', ({ frame, width, height, axis, extent }) => {
    expect(
        adaptiveLayout(width, height, 0, 0, [{ kind: 'division', occludesContent: false, frame }], true)
    ).toMatchObject({ paired: true, paneAxis: axis, inboxExtent: extent, paneGap: 20 })
})
