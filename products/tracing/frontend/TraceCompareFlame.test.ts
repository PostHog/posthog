import { TreeNode, pruneToLineage } from './TraceCompareFlame'

function node(serviceName: string, name: string, children: TreeNode[] = []): TreeNode {
    return { serviceName, name, node: null, previousNode: null, children }
}

function names(n: TreeNode): { name: string; children: ReturnType<typeof names>[] } {
    return { name: n.name, children: n.children.map(names) }
}

describe('pruneToLineage', () => {
    const targetDirectChild = node('', '<ROOT>', [
        node('svc', 'target', [node('svc', 'leaf-a'), node('svc', 'leaf-b')]),
        node('svc', 'sibling', [node('svc', 'sibling-leaf')]),
    ])

    const targetDeep = node('', '<ROOT>', [
        node('svc', 'top', [
            node('svc', 'mid', [
                node('svc', 'target', [node('svc', 'descendant-a'), node('svc', 'descendant-b')]),
                node('svc', 'mid-sibling'),
            ]),
            node('svc', 'top-cousin'),
        ]),
        node('svc', 'other-top'),
    ])

    // Mirrors a cycle that buildTree already broke (svc/loop appears once at depth 1 and is
    // not re-added under itself). pruneToLineage shouldn't care — it walks the already-acyclic
    // tree just like any other.
    const cycleBroken = node('', '<ROOT>', [node('svc', 'loop', [node('svc', 'target', [node('svc', 'tail')])])])

    it.each<[string, TreeNode, string, ReturnType<typeof names>]>([
        ['target not found → original tree', targetDirectChild, 'missing', names(targetDirectChild)],
        [
            'target is direct child of root → drops siblings, keeps target subtree',
            targetDirectChild,
            'target',
            {
                name: '<ROOT>',
                children: [
                    {
                        name: 'target',
                        children: [
                            { name: 'leaf-a', children: [] },
                            { name: 'leaf-b', children: [] },
                        ],
                    },
                ],
            },
        ],
        [
            'target deep in tree → keeps ancestor chain and full descendant subtree',
            targetDeep,
            'target',
            {
                name: '<ROOT>',
                children: [
                    {
                        name: 'top',
                        children: [
                            {
                                name: 'mid',
                                children: [
                                    {
                                        name: 'target',
                                        children: [
                                            { name: 'descendant-a', children: [] },
                                            { name: 'descendant-b', children: [] },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
        [
            'cycle-broken node on lineage path → pruned like any other path',
            cycleBroken,
            'target',
            {
                name: '<ROOT>',
                children: [
                    {
                        name: 'loop',
                        children: [{ name: 'target', children: [{ name: 'tail', children: [] }] }],
                    },
                ],
            },
        ],
    ])('%s', (_label, tree, target, expected) => {
        expect(names(pruneToLineage(tree, target))).toEqual(expected)
    })

    it('returns the original tree by reference when target is missing', () => {
        expect(pruneToLineage(targetDirectChild, 'missing')).toBe(targetDirectChild)
    })
})
