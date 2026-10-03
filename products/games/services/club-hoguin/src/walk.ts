// Where a hedgehog is at a moment of a walk. The server and both clients run this same calculation,
// so a client that knows the walk event never needs the position from the server.
// The copies for the clients are web/walk.js and mod/hooks/walk.js, and a test keeps the three alike.

export interface Walk {
    from: { x: number; y: number }
    path: Array<{ x: number; y: number }>
    // The server clock when the walk started, in milliseconds.
    at: number
}

export interface WalkPosition {
    x: number
    y: number
    facing: 'left' | 'right' | null
    moving: boolean
}

export function positionAt(walk: Walk, speed: number, now: number): WalkPosition {
    let budget = (speed * Math.max(0, now - walk.at)) / 1000
    let x = walk.from.x
    let y = walk.from.y
    let facing: 'left' | 'right' | null = null
    for (const next of walk.path) {
        const distance = Math.hypot(next.x - x, next.y - y)
        if (Math.abs(next.x - x) > 0.01) {
            facing = next.x < x ? 'left' : 'right'
        }
        if (distance > budget) {
            return {
                x: x + ((next.x - x) / distance) * budget,
                y: y + ((next.y - y) / distance) * budget,
                facing,
                moving: true,
            }
        }
        budget -= distance
        x = next.x
        y = next.y
    }
    return { x, y, facing, moving: false }
}
