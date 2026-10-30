import { Meta } from '@storybook/react'
import { useState } from 'react'

import type { MissingSymbolsExamplesApi } from '../../../generated/api.schemas'
import { SourceMapsExamplesBrowser } from './SourceMapsExamplesBrowser'

const meta: Meta<typeof SourceMapsExamplesBrowser> = {
    title: 'ErrorTracking/SourceMapsExamplesBrowser',
    component: SourceMapsExamplesBrowser,
    parameters: {
        viewMode: 'story',
    },
}

export default meta

const EXAMPLES: MissingSymbolsExamplesApi = {
    platform: 'javascript',
    lookback_hours: 24,
    exceptions_loaded: true,
    results: [
        {
            reason: 'chunk_not_uploaded',
            location: '/assets/index-8b1d2e.js',
            symbol_id: '0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b',
            http_status: null,
            frames: 31,
            issues: [
                {
                    id: '01933f1e-0000-7000-8000-000000000001',
                    name: 'TypeError',
                    description: "Cannot read properties of undefined (reading 'total')",
                    occurrences: 212,
                },
                {
                    id: '01933f1e-0000-7000-8000-000000000002',
                    name: 'RangeError',
                    description: 'Invalid time value',
                    occurrences: 1,
                },
            ],
            issue_count: 2,
            issue_count_capped: false,
            example_exception: {
                issue_id: '01933f1e-0000-7000-8000-000000000001',
                fingerprint: 'example-fingerprint',
                timestamp: '2026-10-20T12:00:00Z',
                type: 'TypeError',
                value: "Cannot read properties of undefined (reading 'total')",
                frames: [
                    {
                        function: 'r',
                        source: '/assets/index-8b1d2e.js',
                        line: 1,
                        column: 48213,
                        in_app: true,
                        missing_symbols: true,
                    },
                    {
                        function: 'o',
                        source: '/assets/index-8b1d2e.js',
                        line: 1,
                        column: 39177,
                        in_app: true,
                        missing_symbols: true,
                    },
                    {
                        function: 'callCallback',
                        source: 'react-dom/cjs/react-dom.production.js',
                        line: 4164,
                        column: null,
                        in_app: false,
                        missing_symbols: false,
                    },
                ],
            },
        },
        {
            reason: 'file_not_reachable',
            location: 'https://cdn.example.com/assets/vendor-91ab.js.map',
            symbol_id: null,
            http_status: 404,
            frames: 6,
            issues: [],
            issue_count: 0,
            issue_count_capped: false,
            example_exception: null,
        },
        {
            reason: 'invalid_source_map',
            location: '/assets/admin-7c3d.js',
            symbol_id: null,
            http_status: null,
            frames: 4,
            issues: [],
            issue_count: 0,
            issue_count_capped: false,
            example_exception: null,
        },
    ],
}

function Browser(): JSX.Element {
    const [selectedIndex, setSelectedIndex] = useState(0)
    return (
        <SourceMapsExamplesBrowser
            examples={EXAMPLES}
            selectedIndex={selectedIndex}
            onSelect={setSelectedIndex}
            onRetry={() => {}}
            onOpenException={() => {}}
        />
    )
}

export function MasterDetail(): JSX.Element {
    return (
        // The wide dialog's body width, fixed so the visual baseline does not depend on the viewport.
        <div className="w-[1088px]">
            <Browser />
        </div>
    )
}

export function Narrow(): JSX.Element {
    return (
        // Below the container breakpoint the list stacks above the selected example.
        <div className="w-[520px]">
            <Browser />
        </div>
    )
}
