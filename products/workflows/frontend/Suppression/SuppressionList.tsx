import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight, IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { suppressionListLogic } from './suppressionListLogic'
import type { SuppressionEntry } from './types'

const PAGE_SIZE = 20

export function SuppressionList(): JSX.Element {
    const {
        loadNextPage,
        loadPreviousPage,
        loadSuppressions,
        setShowAddModal,
        setNewIdentifier,
        addSuppression,
        removeSuppression,
    } = useActions(suppressionListLogic)
    const { suppressions, suppressionsLoading, currentPage, showAddModal, addSuppressionLoading, newIdentifier } =
        useValues(suppressionListLogic)

    const columns: LemonTableColumns<SuppressionEntry> = [
        {
            title: 'Recipient',
            dataIndex: 'identifier',
            key: 'identifier',
        },
        {
            title: 'Added by',
            dataIndex: 'source',
            key: 'source',
            render: (source) => (
                <LemonTag type={source === 'MANUAL' ? 'completion' : 'warning'}>
                    {source === 'MANUAL' ? 'Manual' : 'Bounces'}
                </LemonTag>
            ),
        },
        {
            title: 'Reason',
            key: 'reason',
            render: function Render(_, entry: SuppressionEntry): JSX.Element {
                return (
                    <span className="text-muted text-xs">{entry.reason || (entry.last_bounce_diagnostic ?? '—')}</span>
                )
            },
        },
        {
            title: 'Suppressed',
            dataIndex: 'suppressed_at',
            key: 'suppressed_at',
            render: (suppressed_at) => (suppressed_at ? <TZLabel time={suppressed_at as string} /> : <span>—</span>),
        },
        {
            width: 0,
            render: function Render(_, entry: SuppressionEntry): JSX.Element {
                return (
                    <More
                        overlay={
                            <LemonButton
                                status="danger"
                                icon={<IconTrash />}
                                onClick={() => removeSuppression(entry.identifier)}
                                fullWidth
                            >
                                Remove
                            </LemonButton>
                        }
                    />
                )
            },
        },
    ]

    const totalPages = suppressions.count ? Math.ceil(suppressions.count / PAGE_SIZE) : 0
    const showingStart = (currentPage - 1) * PAGE_SIZE + 1
    const showingEnd = Math.min(currentPage * PAGE_SIZE, suppressions.count)

    return (
        <>
            <div className="flex justify-end gap-2 mb-2">
                <LemonButton icon={<IconPlus />} size="small" type="secondary" onClick={() => setShowAddModal(true)}>
                    Add address
                </LemonButton>
                <LemonButton
                    icon={<IconRefresh />}
                    size="small"
                    type="secondary"
                    onClick={loadSuppressions}
                    loading={suppressionsLoading}
                >
                    Reload
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={suppressions.results || []}
                loading={suppressionsLoading}
                loadingSkeletonRows={3}
                rowKey="identifier"
                emptyState="No suppressed addresses. Addresses land here automatically after repeated soft bounces, or when you add them manually."
                size="small"
            />
            {suppressions.count > PAGE_SIZE && (
                <div className="flex items-center justify-between mt-4 px-2">
                    <div className="text-sm text-muted">
                        <span>
                            Showing {showingStart} - {showingEnd} of {suppressions.count.toLocaleString()} addresses
                        </span>
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            icon={<IconChevronLeft />}
                            size="small"
                            disabled={currentPage === 1 || suppressionsLoading}
                            onClick={loadPreviousPage}
                        />
                        <span className="text-sm">
                            Page {currentPage} of {totalPages}
                        </span>
                        <LemonButton
                            icon={<IconChevronRight />}
                            size="small"
                            disabled={!suppressions.next || suppressionsLoading}
                            onClick={loadNextPage}
                        />
                    </div>
                </div>
            )}

            <LemonModal
                isOpen={showAddModal}
                onClose={() => setShowAddModal(false)}
                title="Add address to suppression list"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setShowAddModal(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            loading={addSuppressionLoading}
                            disabled={!newIdentifier.trim()}
                            onClick={() => addSuppression(newIdentifier.trim())}
                        >
                            Add address
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-2">
                    <label htmlFor="suppression-identifier" className="text-sm font-medium">
                        Email address
                    </label>
                    <LemonInput
                        id="suppression-identifier"
                        placeholder="email@example.com"
                        value={newIdentifier}
                        onChange={setNewIdentifier}
                        autoFocus
                        onPressEnter={() => {
                            if (newIdentifier.trim()) {
                                addSuppression(newIdentifier.trim())
                            }
                        }}
                    />
                </div>
            </LemonModal>
        </>
    )
}
