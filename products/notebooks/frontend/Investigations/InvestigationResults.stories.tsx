import type { Meta, StoryObj } from '@storybook/react'

import { investigationExample } from './investigationExample'
import { InvestigationResults } from './InvestigationResults'

const example = investigationExample()
const meta: Meta<typeof InvestigationResults> = {
    title: 'Scenes-App/Notebooks/Investigations/Results',
    component: InvestigationResults,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    decorators: [
        (Story) => (
            <div className="p-4 max-w-3xl">
                <Story />
            </div>
        ),
    ],
    args: { baseline: example.runs[0].results[0] },
}
export default meta
type Story = StoryObj<typeof meta>
export const ChangedMetric: Story = { args: { result: example.runs[1].results[0] } }
export const Table: Story = { args: { result: example.runs[1].results[1], baseline: undefined } }
export const Failed: Story = {
    args: {
        result: { ...example.runs[1].results[0], error: 'Unknown field: conversion. Review the SQL and run again.' },
    },
}
export const ChangedDefinition: Story = {
    args: { result: { ...example.runs[1].results[0], sql: 'SELECT 12 AS conversion_rate' } },
}
