import type { Meta, StoryObj } from '@storybook/react'
// Import from compiled dist instead of source
// @ts-expect-error
import { Graph, Overview, Table } from '../dist/index.esm.js'
import {
    exampleGraphVisitorsResponse,
    exampleOverviewResponse,
    exampleTableResponse,
} from '../../src/stories/exampleData'

const meta: Meta = {
    title: 'Analytics/Overview (Compiled)',
    parameters: {
        layout: 'padded',
        docs: {
            description: {
                component: 'Complete analytics dashboard showcasing all components together - TESTING COMPILED OUTPUT.',
            },
        },
    },
}

export default meta
type Story = StoryObj

export const CompleteDashboard: Story = {
    render: () => (
        <div className="space-y-8 max-w-6xl">
            <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg mb-4">
                <p className="text-sm text-yellow-800">
                    <strong>Testing Compiled Output</strong> - This story uses the built library from `dist/`
                </p>
            </div>

            <div>
                <Overview data={exampleOverviewResponse} />
            </div>

            <div>
                <Graph data={exampleGraphVisitorsResponse} height={300} />
            </div>

            <div>
                <h2 className="text-2xl font-bold mb-4">Pages</h2>
                <Table data={exampleTableResponse} currentPage={1} pageSize={10} />
            </div>
        </div>
    ),
    parameters: {
        docs: {
            description: {
                story: 'A complete analytics dashboard testing the compiled library output.',
            },
        },
    },
}

export const CompleteDashboardDark: Story = {
    render: () => (
        <div className="dark">
            <div className="bg-background text-foreground min-h-screen p-6">
                <div className="space-y-8 max-w-6xl">
                    <div className="p-4 bg-yellow-900/20 border border-yellow-600/30 rounded-lg mb-4">
                        <p className="text-sm text-yellow-200">
                            🧪 <strong>Testing Compiled Output</strong> - This story uses the built library from `dist/`
                        </p>
                    </div>

                    <div>
                        <Overview data={exampleOverviewResponse} />
                    </div>

                    <div>
                        <Graph data={exampleGraphVisitorsResponse} height={300} />
                    </div>

                    <div>
                        <h2 className="text-2xl font-bold mb-4">Pages</h2>
                        <Table data={exampleTableResponse} currentPage={1} pageSize={10} />
                    </div>
                </div>
            </div>
        </div>
    ),
    parameters: {
        docs: {
            description: {
                story: 'A complete analytics dashboard in dark mode testing the compiled library output.',
            },
        },
    },
}
