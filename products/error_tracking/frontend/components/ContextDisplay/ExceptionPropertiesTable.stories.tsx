import type { Meta, StoryObj } from '@storybook/react'

import { ExceptionPropertiesTable } from './ExceptionPropertiesTable'

const meta: Meta<typeof ExceptionPropertiesTable> = {
    title: 'ErrorTracking/ExceptionPropertiesTable',
    component: ExceptionPropertiesTable,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
    decorators: [
        (Story) => (
            <div className="max-w-3xl">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof ExceptionPropertiesTable>

export const Default: Story = {
    args: {
        sections: [
            {
                id: 'built-in-properties',
                title: 'Built-in properties',
                entries: [
                    { key: 'Level', value: 'error', filterKey: '$exception_level' },
                    { key: 'Library', value: 'web 1.234.6', filterKey: '$lib', filterValue: 'web' },
                    { key: 'Browser', value: 'Chrome 134', filterKey: '$browser', filterValue: 'Chrome' },
                    { key: 'OS', value: 'Mac OS X 10.15.7', filterKey: '$os', filterValue: 'Mac OS X' },
                    { key: 'URL', value: 'https://example.com/example/path', filterKey: '$current_url' },
                ],
            },
            {
                id: 'custom-properties',
                title: 'Custom properties',
                entries: [
                    ['Account plan', 'business'],
                    ['Attempt count', 3],
                    ['Feature enabled', true],
                ],
            },
        ],
        onFilterValue: () => {},
    },
}

export const Empty: Story = {
    args: {
        sections: [],
    },
}
