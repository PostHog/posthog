import { LemonButton, LemonTable, LemonTableColumns, LemonModal } from '@posthog/lemon-ui'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { TZLabel } from 'lib/components/TZLabel'
import { OptOutEntry, optOutListLogic } from './optOutListLogic'
import { useActions, useValues } from 'kea'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableNode, ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { MessageCategory } from './optOutCategoriesLogic'
import { IconExternal } from '@posthog/icons'

export function OptOutList({ category }: { category?: MessageCategory }): JSX.Element {
    const logic = optOutListLogic({ category })
    const { setSelectedIdentifier, openPreferencesPage } = useActions(logic)
    const { selectedIdentifier, optOutPersons, optOutPersonsLoading, preferencesUrlLoading } = useValues(logic)

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

    return (
        <>
            <div className="max-h-64 overflow-y-auto">
                <LemonTable
                    columns={columns}
                    dataSource={optOutPersons}
                    loading={optOutPersonsLoading}
                    loadingSkeletonRows={3}
                    rowKey="identifier"
                    emptyState={`No opt-outs found${category?.name ? ` for ${category.name}` : ''}`}
                    size="small"
                />
            </div>

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
        </>
    )
}
