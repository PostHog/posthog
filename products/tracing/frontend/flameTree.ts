import type { SpanTreeNode } from '~/queries/schema/schema-general'

/** One bar of TraceCompareFlame: the calls of one operation, with the operations they call as children. */
export interface FlameTreeNode {
    serviceName: string
    name: string
    node: SpanTreeNode | null
    previousNode: SpanTreeNode | null
    children: FlameTreeNode[]
}

interface PathEntry {
    node: FlameTreeNode
    parent: PathEntry | null
}

/**
 * The nodes from a child of `root` down to the first node that `matches`, in depth-first order with the earlier
 * sibling first. Null when no node matches. Iterative, so that a tree thousands of levels deep cannot overflow the
 * call stack. Each stack entry links to the entry of its parent, so only the match pays for its path.
 */
export function findFlamePath(root: FlameTreeNode, matches: (node: FlameTreeNode) => boolean): FlameTreeNode[] | null {
    const stack: PathEntry[] = []
    const pushChildren = (node: FlameTreeNode, parent: PathEntry | null): void => {
        // Reversed, so that the first child comes off the stack first.
        for (let i = node.children.length - 1; i >= 0; i--) {
            stack.push({ node: node.children[i], parent })
        }
    }
    pushChildren(root, null)
    while (stack.length > 0) {
        const entry = stack.pop()!
        if (matches(entry.node)) {
            const path: FlameTreeNode[] = []
            for (let step: PathEntry | null = entry; step; step = step.parent) {
                path.push(step.node)
            }
            return path.reverse()
        }
        pushChildren(entry.node, entry)
    }
    return null
}

/** The number of nodes in the subtree of `node`, itself included. Iterative for the same reason as `findFlamePath`. */
export function countFlameNodes(node: FlameTreeNode): number {
    let count = 0
    const stack = [node]
    while (stack.length > 0) {
        count += 1
        for (const child of stack.pop()!.children) {
            stack.push(child)
        }
    }
    return count
}
