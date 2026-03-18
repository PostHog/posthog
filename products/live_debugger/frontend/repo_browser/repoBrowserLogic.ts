import _Fuse from 'fuse.js'
import { actions, events, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import {
    GitHubFileContent,
    GitHubTreeItem,
    GitHubTreeResponse,
    loadFileContent,
    loadRepositoryTree,
} from './githubClient'
import type { repoBrowserLogicType } from './repoBrowserLogicType'

// Hack so kea-typegen picks up the type
export type Fuse<T> = _Fuse<T>

export const repoBrowserLogic = kea<repoBrowserLogicType>([
    path(['products', 'live_debugger', 'frontend', 'repo_browser', 'repoBrowserLogic']),

    actions({
        setFileSearchQuery: (query: string) => ({ query }),
        loadFileContent: (filePath: string) => ({ filePath }),
        setExpandedFolderPaths: (paths: string[]) => ({ paths }),
    }),

    loaders(() => ({
        repositoryTree: [null as GitHubTreeResponse | null, { loadRepositoryTree: async () => loadRepositoryTree() }],
        fileContent: [
            null as GitHubFileContent | null,
            { loadFileContent: async ({ filePath }) => loadFileContent(filePath) },
        ],
    })),

    reducers({
        fileSearchQuery: [
            '',
            {
                setFileSearchQuery: (_, { query }) => query,
            },
        ],
        repositoryTree: [
            null as GitHubTreeResponse | null,
            {
                repositoryTreeSuccess: (_, { repositoryTree }) => repositoryTree,
            },
        ],
        fileContent: [
            null as GitHubFileContent | null,
            {
                fileContentSuccess: (_, { fileContent }) => fileContent,
            },
        ],
        selectedFilePath: [
            null as string | null,
            {
                loadFileContent: (_, { filePath }) => filePath,
            },
        ],
    }),

    selectors({
        codeLines: [
            (s) => [s.fileContent],
            (fileContent: GitHubFileContent | null): string[] => {
                if (!fileContent) {
                    return []
                }

                return fileContent.content.split('\n')
            },
        ],
        relevantFiles: [
            (s) => [s.repositoryTree],
            (tree: GitHubTreeResponse): GitHubTreeItem[] => {
                if (!tree) {
                    return []
                }

                return tree.tree.filter(
                    (item) => item.type === 'tree' || (item.type === 'blob' && item.path.endsWith('.py'))
                )
            },
        ],
        fuzzyIndex: [
            (s) => [s.relevantFiles],
            (relevantFiles: GitHubTreeItem[]): Fuse<GitHubTreeItem> => {
                return new _Fuse(relevantFiles, {
                    keys: ['path', 'name'],
                    threshold: 0.3,
                })
            },
        ],
        visibleFilesAndFolders: [
            (s) => [s.fileSearchQuery, s.relevantFiles, s.fuzzyIndex],
            (
                fileSearchQuery: string,
                relevantFiles: GitHubTreeItem[],
                fuzzyIndex: Fuse<GitHubTreeItem>
            ): GitHubTreeItem[] => {
                if (fileSearchQuery) {
                    return fuzzyIndex.search(fileSearchQuery).map((r) => r.item)
                }

                return relevantFiles
            },
        ],
        treeData: [
            (s) => [s.visibleFilesAndFolders],
            (visibleFilesAndFolders: GitHubTreeItem[]): TreeDataItem[] => {
                if (!visibleFilesAndFolders) {
                    return []
                }

                // NOTE(Marce): The assumption is a folder will always appear before
                // the containing items in the return data. It seems to hold.
                const folders = new Map<string, TreeDataItem>()
                const rootElements: TreeDataItem[] = []

                visibleFilesAndFolders.forEach((item: GitHubTreeItem) => {
                    const { pathPrefix, filename, fullPath } = extractPathAndFilename(item)

                    const recordType = item.type === 'tree' ? 'folder' : 'file'
                    const children = item.type === 'tree' ? [] : undefined

                    const parent = folders.get(pathPrefix)
                    const newNode: TreeDataItem = {
                        id: item.sha,
                        name: filename,
                        record: { type: recordType, fullPath: fullPath },
                        children,
                    }

                    if (parent) {
                        // NOTE(Marce): We initialize all folders with an empty
                        // childrens array, so this is safe to do here.
                        parent.children!.push(newNode)
                        parent.children?.sort(filesSortFn)
                    } else {
                        rootElements.push(newNode)
                    }

                    if (item.type === 'tree') {
                        folders.set(fullPath, newNode)
                    }
                })

                rootElements.sort(filesSortFn)
                return rootElements
            },
        ],
    }),

    events(({ actions }) => ({
        afterMount: [actions.loadRepositoryTree],
    })),
])

function extractPathAndFilename(item: GitHubTreeItem): { pathPrefix: string; filename: string; fullPath: string } {
    // This is very hacky, probably need to use a path handling library
    const sections = item.path.split('/')
    const filename = sections.at(-1)!
    const pathPrefix = sections.slice(0, -1).join('/')

    return { filename, fullPath: item.path, pathPrefix }
}

function filesSortFn(a: TreeDataItem, b: TreeDataItem): -1 | 0 | 1 {
    if (a.record!.type !== b.record!.type) {
        if (a.record!.type === 'folder') {
            return -1
        }
        return 1
    }

    if (a.name < b.name) {
        return -1
    } else if (b.name < a.name) {
        return 1
    }
    return 0
}
