import { type ChangeTypes, type FileDiffMetadata } from '@pierre/diffs'

/** One changed file, reduced to what the file tree and its rows need. */
export interface DiffFileSummary {
    path: string
    changeType: ChangeTypes
    additions: number
    deletions: number
}

export interface DiffTreeFile extends DiffFileSummary {
    kind: 'file'
    name: string
}

export interface DiffTreeFolder {
    kind: 'folder'
    /** Full directory path, so it stays a stable id when the display name is a joined chain. */
    path: string
    /** Display name: one segment, or a `a/b/c` chain when the folders in between hold nothing else. */
    name: string
    children: DiffTreeNode[]
}

export type DiffTreeNode = DiffTreeFile | DiffTreeFolder

export function summarizeDiffFile(file: FileDiffMetadata): DiffFileSummary {
    let additions = 0
    let deletions = 0
    for (const hunk of file.hunks) {
        additions += hunk.additionLines
        deletions += hunk.deletionLines
    }
    return { path: file.name, changeType: file.type, additions, deletions }
}

interface MutableFolder {
    path: string
    name: string
    folders: Map<string, MutableFolder>
    files: DiffTreeFile[]
}

function insertFile(root: MutableFolder, file: DiffFileSummary): void {
    const segments = file.path.split('/')
    const name = segments.pop() ?? file.path
    let folder = root
    for (const segment of segments) {
        let child = folder.folders.get(segment)
        if (!child) {
            child = {
                path: folder.path ? `${folder.path}/${segment}` : segment,
                name: segment,
                folders: new Map(),
                files: [],
            }
            folder.folders.set(segment, child)
        }
        folder = child
    }
    folder.files.push({ kind: 'file', name, ...file })
}

const byName = (a: { name: string }, b: { name: string }): number => a.name.localeCompare(b.name)

/**
 * Folders first, then files, each alphabetical. A folder whose only content is one folder collapses
 * into it (`frontend/src/scenes/invites`), the way GitHub's file tree does, so a deep path costs one
 * row instead of four.
 */
function finalizeFolder(folder: MutableFolder): DiffTreeNode[] {
    const folders = [...folder.folders.values()].sort(byName).map((child): DiffTreeFolder => {
        let current = child
        while (current.files.length === 0 && current.folders.size === 1) {
            const [only] = current.folders.values()
            current = { ...only, name: `${current.name}/${only.name}` }
        }
        return { kind: 'folder', path: current.path, name: current.name, children: finalizeFolder(current) }
    })
    const files = [...folder.files].sort(byName)
    return [...folders, ...files]
}

/** Nested folder/file tree for a diff's changed files, ready to render. */
export function buildDiffFileTree(files: DiffFileSummary[]): DiffTreeNode[] {
    const root: MutableFolder = { path: '', name: '', folders: new Map(), files: [] }
    for (const file of files) {
        insertFile(root, file)
    }
    return finalizeFolder(root)
}
