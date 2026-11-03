import { PinScrollAnchor, pinAnchorOffset } from './PinScrollAnchor'

test('retains an accepted approximate scroll until measured native offset correction completes', () => {
    const anchor = new PinScrollAnchor()
    const scroll = jest.fn(() => true)
    anchor.start('pin-49')

    anchor.attempt(scroll)
    expect(anchor.target).toBe('pin-49')
    anchor.measure(['pin-47', 'pin-48'], anchor.version)
    anchor.attempt(scroll)
    expect(anchor.target).toBe('pin-49')

    anchor.measure(['pin-49', 'pin-50'], anchor.version)
    anchor.attempt(() => false)
    expect(anchor.target).toBe('pin-49')
    anchor.attempt(scroll)
    expect(anchor.target).toBeNull()
    expect(scroll.mock.calls).toEqual([['pin-49'], ['pin-49'], ['pin-49']])
})

test('keeps a measured target when synchronous index failure requires another exact scroll', () => {
    const anchor = new PinScrollAnchor()
    anchor.start('pin-49')
    anchor.measure(['pin-49'], anchor.version)
    anchor.attempt(() => {
        anchor.fail()
        return true
    })
    expect(anchor.target).toBe('pin-49')

    anchor.attempt(() => true)
    expect(anchor.target).toBeNull()
})

test.each(['drag or unmount', 'new layout'] as const)('%s cancels stale restoration work', (reason) => {
    const anchor = new PinScrollAnchor()
    anchor.start('pin-49')
    const previousVersion = anchor.version
    anchor.attempt(() => true)

    if (reason === 'new layout') {
        anchor.start('pin-49')
    } else {
        anchor.cancel()
    }
    anchor.measure(['pin-49'], previousVersion)
    const retry = jest.fn(() => true)
    anchor.attempt(retry)

    if (reason === 'new layout') {
        expect(anchor.target).toBe('pin-49')
        anchor.measure(['pin-49'], anchor.version)
        anchor.attempt(retry)
        expect(anchor.target).toBeNull()
    } else {
        expect(retry).not.toHaveBeenCalled()
        expect(anchor.target).toBeNull()
    }
})

test.each([
    [500, 200, 2000, 600, 700],
    [500, -800, 2000, 600, 0],
    [1300, 200, 2000, 600, 1400],
    [0, 80, 200, 600, 0],
])('keeps viewport correction within scrollable bounds %#', (offset, delta, content, viewport, expected) => {
    expect(pinAnchorOffset(offset, delta, content, viewport)).toBe(expected)
})

test('late row layout rechecks a verified anchor in the same layout generation', () => {
    const anchor = new PinScrollAnchor()
    anchor.start('pin-49')
    const version = anchor.version
    anchor.measure(['pin-49'], version)
    anchor.attempt(() => true)
    expect(anchor.target).toBeNull()

    anchor.recheck()
    expect(anchor.target).toBe('pin-49')
    expect(anchor.version).toBe(version)
    expect(anchor.isMeasured).toBe(true)
    anchor.attempt(() => false)
    expect(anchor.target).toBe('pin-49')
    anchor.attempt(() => true)
    expect(anchor.target).toBeNull()
})

test.each(['cancel', 'new layout'] as const)(
    '%s prevents a late measurement from restoring a completed anchor',
    (reason) => {
        const anchor = new PinScrollAnchor()
        anchor.start('pin-49')
        anchor.measure(['pin-49'], anchor.version)
        anchor.attempt(() => true)

        if (reason === 'cancel') anchor.cancel()
        else anchor.start('pin-60')
        anchor.recheck()
        expect(anchor.target).toBe(reason === 'cancel' ? null : 'pin-60')
        expect(anchor.isMeasured).toBe(false)
    }
)
