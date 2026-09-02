import { useMemo, useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonTree, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { buildDiffFileTree, DiffFileSummary, DiffTreeNode } from './diffFileTree'
import { FileChangeIcon } from './PullRequestDiffView'

function toTreeItems(nodes: DiffTreeNode[]): TreeDataItem[] {
    return nodes.map((node) =>
        node.kind === 'folder'
            ? {
                  id: `folder:${node.path}`,
                  name: node.name,
                  record: { type: 'folder' },
                  children: toTreeItems(node.children),
              }
            : {
                  id: node.path,
                  name: node.name,
                  icon: <FileChangeIcon changeType={node.changeType} />,
                  record: {
                      type: 'changed-file',
                      path: node.path,
                      additions: node.additions,
                      deletions: node.deletions,
                  },
              }
    )
}

/**
 * GitHub-style file tree beside the diff: a path filter, then the changed files grouped by directory,
 * each with its status icon and line counts. Selecting a file hands its path back to the parent, which
 * owns the scroll and the highlighted row.
 */
export function PullRequestFileTree({
    files,
    activePath,
    onSelectFile,
}: {
    files: DiffFileSummary[]
    /** Path of the file the diff is currently showing; its row renders active. */
    activePath: string | null
    onSelectFile: (path: string) => void
}): JSX.Element {
    const [query, setQuery] = useState('')
    const data = useMemo(() => {
        const needle = query.trim().toLowerCase()
        const matching = needle ? files.filter((file) => file.path.toLowerCase().includes(needle)) : files
        return toTreeItems(buildDiffFileTree(matching))
    }, [files, query])

    return (
        <div className="flex flex-col gap-2">
            <LemonInput
                type="search"
                size="small"
                placeholder="Filter files"
                value={query}
                onChange={setQuery}
                data-attr="inbox-pr-file-tree-filter"
            />
            {data.length === 0 ? (
                <p className="m-0 px-2 py-1 text-xs text-tertiary">No files match.</p>
            ) : (
                <LemonTree
                    data={data}
                    expandAllFolders
                    isItemActive={(item) => item.id === activePath}
                    onItemClick={(item) => {
                        const path = item?.record?.path
                        if (typeof path === 'string') {
                            onSelectFile(path)
                        }
                    }}
                    renderItem={(item, name) =>
                        item.record?.type === 'changed-file' ? (
                            <span className="flex items-center gap-2 min-w-0" title={item.record.path}>
                                <span className="truncate font-mono text-xs">{name}</span>
                                <span className="ml-auto flex shrink-0 items-center gap-1.5 font-mono text-[0.6875rem] tabular-nums">
                                    {item.record.deletions > 0 && (
                                        <span className="text-danger">-{item.record.deletions}</span>
                                    )}
                                    {item.record.additions > 0 && (
                                        <span className="text-success">+{item.record.additions}</span>
                                    )}
                                </span>
                            </span>
                        ) : (
                            name
                        )
                    }
                />
            )}
        </div>
    )
}
