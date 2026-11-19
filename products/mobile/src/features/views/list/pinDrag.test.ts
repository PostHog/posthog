import { dragScrollStep, dropPin, nearestPin, type PinFrame } from './pinDrag'

const ids = ['chart', 'number', 'row', 'dashboard']

test.each([
    ['chart', 'dashboard', ['number', 'row', 'dashboard', 'chart']],
    ['dashboard', 'number', ['chart', 'dashboard', 'number', 'row']],
    ['number', 'number', ids],
    ['removed', 'row', ids],
    ['chart', 'removed', ids],
])('drops %s at %s without losing or swapping other pins', (source, target, expected) => {
    expect(dropPin(ids, source, target)).toEqual(expected)
    expect(ids).toEqual(['chart', 'number', 'row', 'dashboard'])
})

const frames: PinFrame[] = [
    { id: 'chart', x: 16, y: 100, width: 300, height: 280 },
    { id: 'number', x: 332, y: 100, width: 300, height: 160 },
    { id: 'row', x: 16, y: 396, width: 616, height: 64 },
]

test.each([
    [200, 300, 'chart'],
    [450, 180, 'number'],
    [450, 300, 'number'],
    [450, 430, 'row'],
    [200, 50, 'chart'],
    [200, 600, 'row'],
])('finds a destination at (%s, %s) across unequal tiles and columns', (x, y, id) => {
    expect(nearestPin(frames, x, y)?.id).toBe(id)
})

test('has no drop target before any tiles are measured', () => {
    expect(nearestPin([], 20, 20)).toBeNull()
})

test('edge scrolling is bounded and stops in the middle of the viewport', () => {
    expect(dragScrollStep(100, 100, 700)).toBe(-8)
    expect(dragScrollStep(132, 100, 700)).toBe(-4)
    expect(dragScrollStep(400, 100, 700)).toBe(0)
    expect(dragScrollStep(668, 100, 700)).toBe(4)
    expect(dragScrollStep(800, 100, 700)).toBe(8)
})
