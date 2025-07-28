import React from 'react'
import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

interface OptOutEntry {
    id: string
    identifier: string
    optOutDate: string
}

export function OptOutByCategory(): JSX.Element {
    const [selectedCategory, setSelectedCategory] = React.useState<string>('')

    // Stub data - will be replaced with real data from API
    const optOutEntries: OptOutEntry[] = []

    const columns: LemonTableColumns<OptOutEntry> = [
        {
            title: 'Email/Identifier',
            dataIndex: 'identifier',
            key: 'identifier',
        },
        {
            title: 'Opt-out Date',
            dataIndex: 'optOutDate',
            key: 'optOutDate',
            render: (date: string | undefined) => (date ? new Date(date).toLocaleDateString() : ''),
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-4">
                <label>Category:</label>
                <LemonSelect
                    value={selectedCategory}
                    onChange={setSelectedCategory}
                    options={[
                        { label: 'Select a category...', value: '' },
                        // Will be populated with actual categories
                    ]}
                    placeholder="Select a marketing category"
                />
            </div>

            <LemonTable
                columns={columns}
                dataSource={optOutEntries}
                rowKey="id"
                emptyState={
                    selectedCategory ? 'No opt-outs found for this category' : 'Select a category to view opt-outs'
                }
            />
        </div>
    )
}
