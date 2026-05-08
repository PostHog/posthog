import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight, IconExternal, IconPlus, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { ActorsQuery, DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import type { MessageCategory } from './optOutCategoriesLogic'
import { optOutListLogic } from './optOutListLogic'
import type { OptOutEntry } from './types'

export function OptOutList({ category }: { category?: MessageCategory }): JSX.Element {
    const logic = optOutListLogic({ category })
    const {
        setSelectedIdentifier,
        openPreferencesPage,
        loadNextPage,
        loadPreviousPage,
        loadOptOutPersons,
        openAddOptOutModal,
        closeAddOptOutModal,
        setAddOptOutIdentifier,
        submitAddOptOut,
    } = useActions(logic)
    const {
        selectedIdentifier,
        optOutPersons,
        optOutPersonsLoading,
        preferencesUrlLoading,
        currentPage,
        addOptOutModalOpen,
        addOptOutIdentifier,
        addOptOutSubmitting,
    } = useValues(logic)

    const handleShowPersons = (identifier: string): void => {
        setSelectedIdentifier(identifier)
    }

    const handleCloseModal = (): void => {
        setSelectedIdentifier(null)
    }

    // Create ActorsQuery for the selected identifier
    const actorsQuery: DataTableNode | null = selectedIdentifier
        ? {
              kind: NodeKind.DataTableNode,
              source: {
                  kind: NodeKind.ActorsQuery,
                  select: ['person_display_name -- Person', 'id', 'created_at'],
                  search: selectedIdentifier,
                  orderBy: ['created_at'],
              } as ActorsQuery,
          }
        : null

    const columns: LemonTableColumns<OptOutEntry> = [
        {
            title: 'Recipient',
            dataIndex: 'identifier',
            key: 'recipient',
        },
        {
            title: 'Opt-out date',
            dataIndex: 'updated_at',
            key: 'updated_at',
            render: (updated_at) => <TZLabel time={updated_at as string} />,
        },
        {
            width: 0,
            render: function Render(_, optOutEntry: OptOutEntry): JSX.Element {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton onClick={() => handleShowPersons(optOutEntry.identifier)} fullWidth>
                                    Show person(s)
                                </LemonButton>
                                <LemonButton
                                    onClick={() => openPreferencesPage(optOutEntry.identifier)}
                                    loading={preferencesUrlLoading}
                                    fullWidth
                                    icon={<IconExternal />}
                                >
                                    Manage
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    const totalPages = optOutPersons.count ? Math.ceil(optOutPersons.count / 20) : 0
    const showingStart = (currentPage - 1) * 20 + 1
    const showingEnd = Math.min(currentPage * 20, optOutPersons.count)

    const addOptOutTitle = category?.name ? `Add opt-out for ${category.name}` : 'Add opt-out'

    return (
        <>
            <div className="flex justify-end gap-2 mb-2 mt-[-3rem]">
                <LemonButton
                    icon={<IconPlus />}
                    size="small"
                    type="secondary"
                    onClick={openAddOptOutModal}
                    data-attr="add-opt-out-button"
                >
                    Add opt-out
                </LemonButton>
                <LemonButton
                    icon={<IconRefresh />}
                    size="small"
                    type="secondary"
                    onClick={loadOptOutPersons}
                    loading={optOutPersonsLoading}
                >
                    Reload
                </LemonButton>
            </div>
            <div className="max-h-64 overflow-y-auto">
                <LemonTable
                    columns={columns}
                    dataSource={optOutPersons.results || []}
                    loading={optOutPersonsLoading}
                    loadingSkeletonRows={3}
                    rowKey="identifier"
                    emptyState={`No opt-outs found${category?.name ? ` for ${category.name}` : ''}`}
                    size="small"
                />
            </div>
            {optOutPersons.count > 20 && (
                <div className="flex items-center justify-between mt-4 px-2">
                    <div className="text-sm text-muted">
                        {optOutPersons.count > 0 && (
                            <span>
                                Showing {showingStart} - {showingEnd} of {optOutPersons.count.toLocaleString()} opt-outs
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            icon={<IconChevronLeft />}
                            size="small"
                            disabled={currentPage === 1 || optOutPersonsLoading}
                            onClick={loadPreviousPage}
                        />
                        <span className="text-sm">
                            Page {currentPage} of {totalPages}
                        </span>
                        <LemonButton
                            icon={<IconChevronRight />}
                            size="small"
                            disabled={!optOutPersons.next || optOutPersonsLoading}
                            onClick={loadNextPage}
                        />
                    </div>
                </div>
            )}

            <LemonModal
                isOpen={Boolean(selectedIdentifier)}
                onClose={handleCloseModal}
                title={`Persons for ${selectedIdentifier}`}
                width="50rem"
                footer={null}
            >
                {actorsQuery && (
                    <div className="h-96">
                        <DataTable
                            query={actorsQuery}
                            setQuery={() => {}} // Read-only
                            uniqueKey={`opt-out-persons-${selectedIdentifier}`}
                            readOnly
                        />
                    </div>
                )}
            </LemonModal>

            <LemonModal
                isOpen={addOptOutModalOpen}
                onClose={closeAddOptOutModal}
                title={addOptOutTitle}
                description={
                    category?.name
                        ? `The recipient will be opted out of "${category.name}".`
                        : 'The recipient will be opted out of all marketing communications.'
                }
                footer={
                    <div className="flex gap-2 justify-end">
                        <LemonButton type="secondary" onClick={closeAddOptOutModal} disabledReason={undefined}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={submitAddOptOut}
                            loading={addOptOutSubmitting}
                            disabledReason={!addOptOutIdentifier.trim() ? 'Enter an email or identifier' : undefined}
                            data-attr="add-opt-out-submit"
                        >
                            Add opt-out
                        </LemonButton>
                    </div>
                }
            >
                <LemonInput
                    type="email"
                    autoFocus
                    placeholder="recipient@example.com"
                    value={addOptOutIdentifier}
                    onChange={setAddOptOutIdentifier}
                    onPressEnter={submitAddOptOut}
                    data-attr="add-opt-out-input"
                />
            </LemonModal>
        </>
    )
}
