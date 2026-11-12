import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconArrowLeft, IconFolder, IconLetter } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { parentPath } from '~/layout/panel-layout/ProjectTree/utils'

import { serializeFacetQuery } from './FacetSearchBar/facetQuery'
import { WorkflowFolderPath } from './WorkflowFolderPath'
import { WorkflowFolderRow } from './WorkflowFolderRow'
import { workflowFoldersLogic, type WorkflowFolderFileRow } from './workflowFoldersLogic'
import { buildWorkflowsListV2Columns } from './workflowsListV2Columns'
import { workflowsListV2Logic } from './workflowsListV2Logic'

type ContentsRow =
    | WorkflowFolderFileRow
    | { kind: 'folder' | 'up'; id: string; name: string; path: string; count: number }

const SORTING_URL_PARAM = 'order'

const ROW_KIND_RANK: Record<ContentsRow['kind'], number> = {
    up: 0,
    folder: 1,
    workflow: 2,
    email_template: 3,
}

function isNavigationRow(row: ContentsRow): row is Extract<ContentsRow, { kind: 'folder' | 'up' }> {
    return row.kind === 'folder' || row.kind === 'up'
}

export function WorkflowFolderContents(): JSX.Element {
    const {
        folderRows,
        folderTemplates,
        folderFileRows,
        childFolders,
        currentFolder,
        browserReady,
        browserReadyLoading,
        hasActiveQuery,
        otherProductFileCount,
    } = useValues(workflowFoldersLogic)
    const { openFolder } = useActions(workflowFoldersLogic)
    const {
        shownColumns,
        metricsLoading,
        listLoaded,
        listComplete,
        serverSearchStatus,
        hasHealthFilter,
        metricsLoaded,
        value,
    } = useValues(workflowsListV2Logic)
    // Health pills match nothing until run metrics arrive, so wait instead of showing an empty folder.
    const healthPending = hasHealthFilter && !metricsLoaded
    // A new folder or filter starts again on page one, as the flag-off list does.
    const filterKey = `${currentFolder ?? ''}\n${serializeFacetQuery(value.filters)}\n${value.text}`
    const [pageForFilter, setPageForFilter] = useState({ filterKey, page: 1 })
    const currentPage = pageForFilter.filterKey === filterKey ? pageForFilter.page : 1
    const { searchParams } = useValues(router)
    const sortOrder = String(searchParams[SORTING_URL_PARAM] ?? '').startsWith('-') ? -1 : 1
    const keepRowKindsInPlace =
        (compareSameKind: (a: ContentsRow, b: ContentsRow) => number) =>
        (a: ContentsRow, b: ContentsRow): number =>
            sortOrder * (ROW_KIND_RANK[a.kind] - ROW_KIND_RANK[b.kind]) || compareSameKind(a, b)
    const rows: ContentsRow[] = [
        ...(currentFolder
            ? [{ kind: 'up' as const, id: 'up', name: '..', path: parentPath(currentFolder), count: 0 }]
            : []),
        ...childFolders.map((folder) => ({ ...folder, kind: 'folder' as const, id: `folder:${folder.path}` })),
        ...folderFileRows,
    ]
    const columns: LemonTableColumns<ContentsRow> = buildWorkflowsListV2Columns(shownColumns, metricsLoading).map(
        (column): LemonTableColumn<ContentsRow, keyof ContentsRow | undefined> => ({
            key: column.key,
            title: column.title,
            width: column.width,
            align: column.align,
            sorter:
                typeof column.sorter === 'function'
                    ? keepRowKindsInPlace((a, b) =>
                          a.kind === 'workflow' && b.kind === 'workflow' && typeof column.sorter === 'function'
                              ? column.sorter(a.row, b.row)
                              : a.name.localeCompare(b.name)
                      )
                    : undefined,
            className: `${typeof column.className === 'string' ? column.className : ''} ${['owner', 'updated_at', 'created_by', 'last_7_days', 'health', 'trigger', 'type'].includes(column.key ?? '') ? 'hidden @min-[48rem]/main-content:table-cell' : ''}`,
            render: (_, item, rowIndex, columnIndex) => {
                if (item.kind === 'workflow') {
                    return column.render?.(undefined, item.row, rowIndex, columnIndex)
                }
                if (column.key === 'name') {
                    if (item.kind === 'folder' || item.kind === 'up') {
                        return (
                            <WorkflowFolderRow icon={item.kind === 'up' ? <IconArrowLeft /> : <IconFolder />}>
                                <LemonButton
                                    size="small"
                                    noPadding
                                    className="flex-1 min-w-0"
                                    onClick={() => openFolder(item.path || null)}
                                    data-attr="workflows-folder-row"
                                >
                                    <span className="truncate mr-1">{item.name}</span>
                                    {item.kind === 'folder' && (
                                        <span
                                            className="text-secondary font-normal text-xs"
                                            translate="no"
                                        >{`(${item.count})`}</span>
                                    )}
                                </LemonButton>
                            </WorkflowFolderRow>
                        )
                    }
                    if (item.kind !== 'email_template') {
                        return null
                    }
                    return (
                        <WorkflowFolderRow icon={<IconLetter />}>
                            <WorkflowFolderPath path={item.entry.path} />
                            <LemonTableLink
                                to={urls.workflowsLibraryTemplate(item.entry.ref ?? '')}
                                title={item.name}
                                truncateTitle
                            />
                        </WorkflowFolderRow>
                    )
                }
                if (item.kind === 'email_template' && column.key === 'status') {
                    return <LemonTag type="muted">Email template</LemonTag>
                }
                return null
            },
        })
    )
    // Rows on pages still to come, or on a page that failed, could land here, so nothing is empty yet.
    const empty = !listComplete
        ? 'Nothing here among the workflows loaded so far.'
        : hasActiveQuery
          ? 'Nothing matches. Remove a filter or the folder to see more.'
          : currentFolder === 'Unfiled'
            ? 'Every workflow and email template is in a folder.'
            : 'This folder is empty.'
    return (
        <>
            {otherProductFileCount > 0 && (
                <div className="text-xs text-secondary mb-1" data-attr="workflows-folder-other-product-files">
                    <span>This folder also holds files from other products. </span>
                    <Link to={urls.projectFiles(currentFolder ?? '')}>Open them in project files</Link>
                </div>
            )}
            <LemonTable
                dataSource={rows}
                columns={columns}
                rowKey="id"
                rowClassName="group/row"
                onRow={(item) =>
                    isNavigationRow(item)
                        ? {
                              className: 'cursor-pointer',
                              onClick: (event) => {
                                  if (!(event.target as HTMLElement).closest('button, a')) {
                                      openFolder(item.path || null)
                                  }
                              },
                          }
                        : {}
                }
                size="small"
                loading={
                    !browserReady ||
                    browserReadyLoading ||
                    !listLoaded ||
                    serverSearchStatus === 'pending' ||
                    healthPending
                }
                pagination={{
                    pageSize: 100,
                    currentPage,
                    onPageChange: (page) => setPageForFilter({ filterKey, page }),
                }}
                emptyState={empty}
                data-attr="workflows-folder-contents"
            />
            {browserReady &&
                !browserReadyLoading &&
                serverSearchStatus !== 'pending' &&
                !healthPending &&
                listLoaded &&
                folderRows.length === 0 &&
                folderTemplates.length === 0 &&
                childFolders.length === 0 &&
                currentFolder && <div className="px-2 py-3 text-sm text-secondary">{empty}</div>}
        </>
    )
}
