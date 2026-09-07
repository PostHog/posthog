import { useActions, useValues } from 'kea'

import {
    IconChevronLeft,
    IconChevronRight,
    IconDownload,
    IconExternal,
    IconPlus,
    IconRefresh,
    IconRevert,
    IconUpload,
} from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { ActorsQuery, DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import type { MessagePreferencesApi } from 'products/messaging/frontend/generated/api.schemas'

import type { MessageCategory } from './optOutCategoriesLogic'
import { optOutListLogic } from './optOutListLogic'

export function OptOutList({ category }: { category?: MessageCategory }): JSX.Element {
    const logic = optOutListLogic({ category })
    const {
        setSelectedIdentifier,
        openPreferencesPage,
        loadNextPage,
        loadPreviousPage,
        loadOptOutPersons,
        setShowAddOptOutModal,
        setNewOptOutIdentifier,
        addOptOut,
        removeOptOut,
        setShowImportCsvModal,
        setCsvFile,
        importCsv,
        exportCsv,
        clearCsvImportResult,
        setSearchTerm,
    } = useActions(logic)
    const {
        selectedIdentifier,
        optOutPersons,
        optOutPersonsLoading,
        preferencesUrlLoading,
        currentPage,
        showAddOptOutModal,
        addOptOutLoading,
        removeOptOutLoading,
        pendingRemoveIdentifier,
        newOptOutIdentifier,
        showImportCsvModal,
        csvFile,
        csvImportProgress,
        csvImportResult,
        csvImportResultLoading,
        csvExportLoading,
        searchTerm,
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

    const columns: LemonTableColumns<MessagePreferencesApi> = [
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
            render: function Render(_, optOutEntry: MessagePreferencesApi): JSX.Element {
                const removingThisRow = removeOptOutLoading && pendingRemoveIdentifier === optOutEntry.identifier
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
                                <LemonButton
                                    onClick={() => removeOptOut(optOutEntry.identifier)}
                                    loading={removingThisRow}
                                    disabledReason={removingThisRow ? 'Removing…' : undefined}
                                    fullWidth
                                    icon={<IconRevert />}
                                >
                                    Remove opt-out
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

    return (
        <>
            <div className="flex flex-wrap justify-end gap-2 mb-2">
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search recipients"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    className="w-60"
                />
                <LemonButton
                    icon={<IconPlus />}
                    size="small"
                    type="secondary"
                    onClick={() => setShowAddOptOutModal(true)}
                >
                    Add opt-out
                </LemonButton>
                <LemonButton
                    icon={<IconUpload />}
                    size="small"
                    type="secondary"
                    onClick={() => {
                        clearCsvImportResult()
                        setShowImportCsvModal(true)
                    }}
                    tooltip="Upload a CSV of recipients to opt out"
                >
                    Import CSV
                </LemonButton>
                <LemonButton
                    icon={<IconDownload />}
                    size="small"
                    type="secondary"
                    onClick={exportCsv}
                    loading={csvExportLoading}
                    tooltip="Download this opt-out list as a CSV"
                >
                    Export CSV
                </LemonButton>
                <LemonButton
                    icon={<IconRefresh />}
                    size="small"
                    type="secondary"
                    onClick={() => loadOptOutPersons()}
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
                    emptyState={
                        searchTerm.trim()
                            ? 'No opt-outs match your search'
                            : `No opt-outs found${category?.name ? ` for ${category.name}` : ''}`
                    }
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
                isOpen={showAddOptOutModal}
                onClose={() => setShowAddOptOutModal(false)}
                title={`Add opt-out${category?.name ? ` for ${category.name}` : ''}`}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setShowAddOptOutModal(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            loading={addOptOutLoading}
                            disabled={!newOptOutIdentifier.trim()}
                            onClick={() => {
                                addOptOut(newOptOutIdentifier.trim())
                            }}
                        >
                            Add opt-out
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-2">
                    <label htmlFor="opt-out-identifier" className="text-sm font-medium">
                        Recipient identifier (e.g. email address)
                    </label>
                    <LemonInput
                        id="opt-out-identifier"
                        placeholder="email@example.com"
                        value={newOptOutIdentifier}
                        onChange={setNewOptOutIdentifier}
                        autoFocus
                        onPressEnter={() => {
                            // Guard against a second Enter mid-flight firing a duplicate POST — the
                            // footer button already disables while loading; mirror that here.
                            if (newOptOutIdentifier.trim() && !addOptOutLoading) {
                                addOptOut(newOptOutIdentifier.trim())
                            }
                        }}
                    />
                </div>
            </LemonModal>

            <LemonModal
                isOpen={showImportCsvModal}
                onClose={() => setShowImportCsvModal(false)}
                title={`Import opt-outs${category?.name ? ` for ${category.name}` : ''}`}
                description="Bring an opt-out list over from another email tool, or bulk add recipients."
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setShowImportCsvModal(false)}>
                            Close
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={importCsv}
                            loading={csvImportResultLoading}
                            disabledReason={!csvFile ? 'Choose a CSV file first' : undefined}
                        >
                            Import
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-3 max-w-160">
                    <p className="mb-0">
                        Upload a CSV with one recipient per row and a column named <code>identifier</code> or{' '}
                        <code>email</code>. Everyone in the file is opted out of{' '}
                        {category?.name ? <b>{category.name}</b> : 'all marketing messages'}, unless the row names a
                        different category in a <code>category_key</code> column.
                    </p>
                    <p className="mb-0 text-muted">
                        Importing never opts anyone back in, so it's safe to upload the same file twice. A file exported
                        from here imports back as-is.
                    </p>
                    {csvFile ? (
                        <div className="flex items-center justify-between border rounded p-3">
                            <div>
                                <div className="font-medium text-sm">{csvFile.name}</div>
                                <div className="text-xs text-muted">{(csvFile.size / 1024).toFixed(1)} KB</div>
                            </div>
                            <LemonButton size="small" type="secondary" onClick={() => setCsvFile(null)}>
                                Remove
                            </LemonButton>
                        </div>
                    ) : (
                        <LemonFileInput
                            accept=".csv"
                            multiple={false}
                            value={[]}
                            onChange={(files) => setCsvFile(files[0] || null)}
                            showUploadedFiles={false}
                            callToAction={
                                <div className="border-2 border-dashed border-border rounded-lg p-4 text-center hover:border-primary-light transition-colors cursor-pointer w-full">
                                    <div className="text-sm text-muted">Drop a CSV file here or click to browse</div>
                                </div>
                            }
                        />
                    )}
                    {csvImportResultLoading && csvImportProgress && csvImportProgress.total > 1000 && (
                        <div className="text-sm text-muted">
                            Processed {csvImportProgress.processed.toLocaleString()} of{' '}
                            {csvImportProgress.total.toLocaleString()} recipients
                        </div>
                    )}
                    {csvImportResult && (
                        <LemonBanner type={csvImportResult.errors.length > 0 ? 'warning' : 'success'}>
                            <div>
                                Added {csvImportResult.opted_out.toLocaleString()} opt-outs from{' '}
                                {csvImportResult.total.toLocaleString()} rows.
                                {csvImportResult.skipped > 0 &&
                                    ` Skipped ${csvImportResult.skipped.toLocaleString()} rows.`}
                            </div>
                            {csvImportResult.errors.length > 0 && (
                                <ul className="mt-2 mb-0 text-xs">
                                    {csvImportResult.errors.map((error) => (
                                        <li key={error}>{error}</li>
                                    ))}
                                </ul>
                            )}
                        </LemonBanner>
                    )}
                </div>
            </LemonModal>
        </>
    )
}
