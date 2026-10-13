import './infrastructureAdmin.css'

import type { Meta, StoryObj } from '@storybook/react'

import { ThemeProvider } from '@posthog/quill'

import { CustomImageInventory } from './CustomImageInventory'
import { Sources, imageNames } from './infrastructureTypes'
import { ReleasePipeline } from './ReleasePipeline'
import { SourceFreshness } from './SourceFreshness'

function exampleSources(): Sources {
    const observed_at = new Date().toISOString()
    const sources: Sources = {
        package: { status: 'ok', observed_at, data: { version: '1.0.0', revision: 'example-revision' } },
        release: { status: 'ok', observed_at, data: { pin: '1.0.0', runs: [] } },
        custom: { status: 'ok', observed_at, data: { images: [], truncated: false, limit: 1000 } },
        dev_stack: {
            status: 'ok',
            observed_at,
            data: {
                name: 'posthog-dev-stack',
                base_image_reference: 'ghcr.io/posthog/posthog-sandbox-vm@sha256:example',
                workflow_url: 'https://example.com/workflow',
            },
        },
    }
    for (const name of imageNames) {
        sources[name] = {
            status: 'ok',
            observed_at,
            data: {
                name,
                reference: `ghcr.io/posthog/posthog-sandbox-${name}@sha256:example`,
                platforms: ['amd64', 'arm64'].map((arch) => ({
                    arch,
                    version: '1.0.0',
                    revision: 'example-revision',
                    base_revision: 'example-revision',
                    inputs_digest: 'example-inputs',
                    digest: 'sha256:example',
                })),
            },
        }
    }
    sources.custom!.data!.images = ['ready', 'building', 'ready'].map((status, index) => ({
        id: `${index + 1}0000000-0000-4000-8000-000000000001`,
        team_id: 1,
        status,
        version: 2,
        base_image_reference:
            index === 0 ? sources.vm!.data!.reference : 'ghcr.io/posthog/posthog-sandbox-vm@sha256:previous',
        base_image_refresh_reference: index === 1 ? sources.vm!.data!.reference : null,
        has_error: index === 2,
        has_published_image: true,
        has_spec: true,
        updated_at: observed_at,
        workflow_url: 'https://example.com/workflow',
    }))
    return sources
}

const meta: Meta<typeof ReleasePipeline> = {
    title: 'Products/Tasks/Infrastructure admin',
    component: ReleasePipeline,
    parameters: { layout: 'fullscreen' },
    decorators: [
        (Story) => (
            <ThemeProvider defaultTheme="light">
                <div className="app-shell">
                    <Story />
                </div>
            </ThemeProvider>
        ),
    ],
}
export default meta
export const RollingOut: StoryObj<typeof ReleasePipeline> = {
    render: () => {
        const sources = exampleSources()
        return (
            <div className="workspace-main">
                <ReleasePipeline sources={sources} selected="custom" onSelect={() => {}} />
                <CustomImageInventory sources={sources} onInspect={() => {}} />
            </div>
        )
    },
}
export const Unavailable: StoryObj<typeof ReleasePipeline> = {
    args: { sources: {}, selected: 'custom', onSelect: () => {} },
}
export const AwaitingPin: StoryObj<typeof ReleasePipeline> = {
    render: () => {
        const sources = exampleSources()
        sources.package!.data!.version = '1.1.0'
        return <ReleasePipeline sources={sources} selected="release" onSelect={() => {}} />
    },
}
export const Narrow: StoryObj<typeof ReleasePipeline> = {
    render: () => (
        <div className="workspace-main w-130">
            <ReleasePipeline sources={exampleSources()} selected="custom" onSelect={() => {}} />
        </div>
    ),
}

export const DataSources: StoryObj<typeof ReleasePipeline> = {
    render: () => {
        const now = Date.parse('2026-01-01T12:00:00Z')
        const sources = exampleSources()
        for (const source of Object.values(sources)) {
            source.observed_at = new Date(now).toISOString()
        }
        sources.release = { status: 'error', observed_at: null, data: null }
        sources.vm!.observed_at = new Date(now - 300_000).toISOString()
        sources.dev_stack!.status = 'refreshing'
        return <SourceFreshness sources={sources} now={now} />
    },
}

export const DataSourcesNarrow: StoryObj<typeof ReleasePipeline> = {
    ...DataSources,
    decorators: [
        (Story) => (
            <div className="w-130 max-w-full">
                <Story />
            </div>
        ),
    ],
}

export const DataSourcesLoading: StoryObj<typeof ReleasePipeline> = {
    render: () => <SourceFreshness sources={{}} now={Date.now()} />,
}

export const LastSeenReleases: StoryObj<typeof ReleasePipeline> = {
    render: () => {
        const sources = exampleSources()
        sources.package!.data!.version = '1.1.0'
        sources.release = { status: 'error', observed_at: null, data: null }
        for (const source of Object.values(sources)) {
            source.status = 'error'
        }
        return <ReleasePipeline sources={sources} selected="base" onSelect={() => {}} />
    },
}
