import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'

import { type QuickScannerLogicProps, quickScannerLogic } from '../quickScannerLogic'
import { QuickScannerPopoverContent } from './QuickScannerPopover'

const quota = {
    credit_limit: 10000,
    credits_used: 100,
    remaining: 9900,
    exhausted: false,
    projected_monthly_credits: 0,
    scanners_monthly_credits: 0,
    backfills_committed_credits: 0,
    free_monthly_credits: 2500,
    credits_settled: 100,
    credits_reserved: 0,
    period_start: '2026-10-01T00:00:00Z',
    period_end: '2026-11-01T00:00:00Z',
}

const estimate = {
    matched_sessions_in_window: 38,
    window_days: 7,
    estimated_observations_per_month: 163,
    credits_per_observation: 2,
    estimated_credits_per_month: 326,
    other_enabled_scanners_monthly_credits: 0,
    active_backfill_credits: 0,
    free_only_monthly_credits_left: 2400,
}

function logicProps(key: string): QuickScannerLogicProps {
    return {
        key,
        entryPoint: 'storybook',
        prefill: {
            name: 'Error tracking: TypeError',
            scanner_type: 'summarizer',
            scanner_config: { prompt: 'Describe what the user experienced.', length: 'medium' },
            query: { kind: NodeKind.RecordingsQuery },
            sampling_rate: 1,
        },
    }
}

const OUTPUT = (
    <ul className="list-disc pl-4 m-0">
        <li>What the user was trying to do</li>
        <li>What they saw when the error happened</li>
        <li>How they reacted</li>
        <li>Whether they recovered or gave up</li>
    </ul>
)

function QuickScannerStory({ storyKey, created }: { storyKey: string; created?: boolean }): JSX.Element {
    const props = logicProps(storyKey)
    const { loadEstimate, createScannerSuccess } = useActions(quickScannerLogic(props))

    useEffect(() => {
        loadEstimate()
        if (created) {
            createScannerSuccess({ id: 'scanner-1' } as any)
        }
    }, [loadEstimate, createScannerSuccess, created])

    return (
        <QuickScannerPopoverContent
            logicProps={props}
            title="Have AI watch every new session with this error"
            recordingsLabel="Sessions that hit this error"
            output={OUTPUT}
        />
    )
}

const meta: Meta<typeof QuickScannerStory> = {
    title: 'Scenes-App/Replay Vision/QuickScannerPopover',
    component: QuickScannerStory,
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/vision/quota/': quota },
            post: { '/api/projects/:team_id/vision/scanners/estimate/': estimate },
        }),
        (Story) => (
            <div className="inline-block rounded border bg-surface-primary p-2">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof QuickScannerStory>

export const BeforeCreate: Story = { args: { storyKey: 'before-create' } }

export const Created: Story = { args: { storyKey: 'created', created: true } }
