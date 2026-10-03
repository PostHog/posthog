// Where a hedgehog is at a moment of a walk. The same calculation as src/walk.ts on the server.
/**
 * @param {{ from: { x: number, y: number }, path: Array<{ x: number, y: number }>, at: number }} walk
 * @param {number} speed
 * @param {number} now the server clock, in milliseconds
 */
export function positionAt(walk, speed, now) {
    let budget = (speed * Math.max(0, now - walk.at)) / 1000
    let x = walk.from.x
    let y = walk.from.y
    let facing = null
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
