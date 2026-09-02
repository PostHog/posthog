import { buildDiffFileTree, DiffFileSummary, DiffTreeNode } from './diffFileTree'

const file = (path: string): DiffFileSummary => ({ path, changeType: 'change', additions: 1, deletions: 0 })

/** `folder/` for folders, the bare name for files, nested as `name(children)`. */
function outline(nodes: DiffTreeNode[]): string {
    return nodes
        .map((node) => (node.kind === 'folder' ? `${node.name}/(${outline(node.children)})` : node.name))
        .join(' ')
}

describe('buildDiffFileTree', () => {
    test.each([
        {
            name: 'collapses a chain of single-child folders into one row',
            paths: ['frontend/src/scenes/invites/inviteLogic.ts', 'frontend/src/scenes/invites/InviteRow.tsx'],
            expected: 'frontend/src/scenes/invites/(inviteLogic.ts InviteRow.tsx)',
        },
        {
            name: 'stops collapsing where a folder holds files of its own',
            paths: ['posthog/api/organization_invite.py', 'posthog/api/test/test_organization_invite.py'],
            expected: 'posthog/api/(test/(test_organization_invite.py) organization_invite.py)',
        },
        {
            name: 'keeps sibling folders apart and lists folders before root files',
            paths: ['b/two.py', 'README.md', 'a/one.py'],
            expected: 'a/(one.py) b/(two.py) README.md',
        },
    ])('$name', ({ paths, expected }) => {
        expect(outline(buildDiffFileTree(paths.map(file)))).toBe(expected)
    })

    it('keeps the full directory path on a collapsed folder', () => {
        const [folder] = buildDiffFileTree([file('frontend/src/scenes/invites/inviteLogic.ts')])
        expect(folder).toMatchObject({ kind: 'folder', path: 'frontend/src/scenes/invites' })
    })
})
