import { Meta } from '@storybook/react'

import { SourceMapsExamplesTable } from './SourceMapsExamplesTable'

const meta: Meta<typeof SourceMapsExamplesTable> = {
    title: 'ErrorTracking/SourceMapsExamplesTable',
    component: SourceMapsExamplesTable,
    parameters: {
        viewMode: 'story',
    },
}

export default meta

export function MixedReasons(): JSX.Element {
    return (
        // The modal's width, fixed so the visual baseline does not depend on the viewport.
        <div className="w-[880px]">
            <SourceMapsExamplesTable
                examples={[
                    {
                        reason: 'no_source_map_linked',
                        location: 'https://app.example.com/_next/static/chunks/main-3f2a1c.js',
                        symbol_id: null,
                        http_status: null,
                        frames: 1412,
                        example_function: 'e',
                    },
                    {
                        reason: 'chunk_not_uploaded',
                        location: '/assets/index-8b1d2e.js',
                        symbol_id: '0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b',
                        http_status: null,
                        frames: 388,
                        example_function: 'handleSubmit',
                    },
                    {
                        reason: 'file_not_reachable',
                        location: 'https://cdn.example.com/assets/vendor-91ab.js.map',
                        symbol_id: null,
                        http_status: 404,
                        frames: 96,
                        example_function: 't',
                    },
                    {
                        reason: 'bundle_not_injected',
                        location: 'index.android.bundle',
                        symbol_id: null,
                        http_status: null,
                        frames: 41,
                        example_function: null,
                    },
                ]}
            />
        </div>
    )
}
