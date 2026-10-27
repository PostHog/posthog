import { countFlameNodes, findFlamePath, type FlameTreeNode } from './flameTree'

const flameNode = (name: string, children: FlameTreeNode[] = []): FlameTreeNode => ({
    serviceName: 'web',
    name,
    node: null,
    previousNode: null,
    children,
})

describe('flameTree', () => {
    // The compare modal focuses the first match in pre-order, earlier siblings first. A walk that takes the last
    // sibling first, or the shallowest match first, focuses the second `cache GET` here.
    it('finds the first match in depth-first order, earlier siblings first', () => {
        const root = flameNode('<ROOT>', [flameNode('GET /x', [flameNode('cache GET')]), flameNode('cache GET')])

        const path = findFlamePath(root, (node) => node.name === 'cache GET')

        expect(path?.map((node) => node.name)).toEqual(['GET /x', 'cache GET'])
    })

    // A recursive walk overflows the call stack on a chain this deep, so a highlight that focuses the leaf throws, and
    // so does a "+N more" bundle that counts the chain.
    it('finds the leaf of a chain 20,000 levels deep, and counts the chain', () => {
        const root = flameNode('<ROOT>')
        let parent = root
        for (let depth = 1; depth <= 20_000; depth++) {
            const child = flameNode(`level ${depth}`)
            parent.children.push(child)
            parent = child
        }

        const path = findFlamePath(root, (node) => node.name === 'level 20000')

        expect(path?.length).toBe(20_000)
        expect(path?.[0].name).toBe('level 1')
        expect(path?.[path.length - 1]).toBe(parent)
        expect(countFlameNodes(root)).toBe(20_001)
    })
})
