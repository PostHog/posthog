import { LemonButton, LemonTable, LemonTableColumns, LemonModal } from '@posthog/lemon-ui'
import { TZLabel } from 'lib/components/TZLabel'
import { OptOutEntry, optOutListLogic } from './optOutListLogic'
import { useActions, useValues } from 'kea'
import { IconPerson } from '@posthog/icons'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableNode, ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { MessageCategory } from './optOutCategoriesLogic'
import { useEffect } from 'react'

export function OptOutList({ category }: { category?: MessageCategory }): JSX.Element {
    const logic = optOutListLogic({ category })
    const { setSelectedIdentifier, loadOptOutPersons } = useActions(logic)
    const { selectedIdentifier, optOutPersons, optOutPersonsLoading } = useValues(logic)

    useEffect(() => {
        // If no category is provided or it's a marketing category, load opt-out persons
        if (!category?.id || category?.category_type === 'marketing') {
            loadOptOutPersons()
        }
    }, [category, loadOptOutPersons])

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
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={() => handleShowPersons(optOutEntry.identifier)}
                        icon={<IconPerson />}
                    >
                        Person(s)
                    </LemonButton>
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
                title={selectedIdentifier ? `Persons for ${selectedIdentifier}` : 'Persons'}
                width="50rem"
                footer={null}
            >
                {actorsQuery && (
                    <div className="h-96">
                        <DataTable
                            query={actorsQuery}
                            setQuery={() => {}} // Read-only mode
                            uniqueKey={`opt-out-persons-${selectedIdentifier}`}
                            readOnly
                        />
                    </div>
                )}
            </LemonModal>
        </>
    )
}
