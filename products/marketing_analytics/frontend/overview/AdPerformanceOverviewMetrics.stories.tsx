import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import type { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import { expect, userEvent } from 'storybook/test'

import { AdPerformanceOverviewMetrics } from './AdPerformanceOverviewMetrics'
import { overviewMetricsLogic } from './overviewMetricsLogic'

const items: OverviewMetricCardItem[] = [
    { key: 'Cost', value: 1800, previous: 1500, changeFromPreviousPct: 20, kind: 'currency', isIncreaseBad: true },
    { key: 'Clicks', value: 4200, previous: 3500, changeFromPreviousPct: 20, kind: 'unit' },
    { key: 'Impressions', value: 90000, previous: 75000, changeFromPreviousPct: 20, kind: 'unit' },
    { key: 'Reported Conversions', value: 60, previous: 50, changeFromPreviousPct: 20, kind: 'unit' },
    { key: 'Reported Conversion Value', value: 3600, previous: 3000, changeFromPreviousPct: 20, kind: 'currency' },
    { key: 'CPC', value: 0.43, previous: 0.43, changeFromPreviousPct: 0, kind: 'currency', isIncreaseBad: true },
    { key: 'CTR', value: 4.67, previous: 4.67, changeFromPreviousPct: 0, kind: 'percentage' },
    {
        key: 'Cost per Reported Conversions',
        value: 30,
        previous: 30,
        changeFromPreviousPct: 0,
        kind: 'currency',
        isIncreaseBad: true,
    },
    { key: 'Reported ROAS', value: 2, previous: 2, changeFromPreviousPct: 0, kind: 'unit' },
    { key: 'Trial started', value: 80, previous: 64, changeFromPreviousPct: 25, kind: 'unit' },
    {
        key: 'Cost Per Trial started',
        value: 22.5,
        previous: 23.44,
        changeFromPreviousPct: -4,
        kind: 'currency',
        isIncreaseBad: true,
    },
    { key: 'Subscription started', value: 20, previous: 16, changeFromPreviousPct: 25, kind: 'unit' },
    {
        key: 'Cost Per Subscription started',
        value: 90,
        previous: 93.75,
        changeFromPreviousPct: -4,
        kind: 'currency',
        isIncreaseBad: true,
    },
]

const meta: Meta<typeof AdPerformanceOverviewMetrics> = {
    title: 'Scenes-App/Marketing Analytics/Overview metrics',
    component: AdPerformanceOverviewMetrics,
    parameters: { layout: 'padded' },
    // The grid breaks on its container's width, and the padded root takes its width from its content.
    decorators: [
        (Story) => (
            <div className="w-[72rem]">
                <Story />
            </div>
        ),
    ],
    args: {
        items,
        loading: false,
        viewKey: 'overview-metrics-story',
        labelFromKey: (key) => key,
    },
}
export default meta

type Story = StoryObj<typeof AdPerformanceOverviewMetrics>

export const Default: Story = {}

export const Narrow: Story = {
    args: { viewKey: 'overview-metrics-narrow-story' },
    decorators: [
        (Story) => (
            <div className="w-lg">
                <Story />
            </div>
        ),
    ],
}

export const MediumWidth: Story = {
    args: { viewKey: 'overview-metrics-medium-story' },
    decorators: [
        (Story) => (
            <div className="w-[38rem]">
                <Story />
            </div>
        ),
    ],
}

export const Loading: Story = {
    args: { viewKey: 'overview-metrics-loading-story', items: [], loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const WithoutGoals: Story = {
    args: { viewKey: 'overview-metrics-no-goals-story', items: items.slice(0, 9) },
}

export const Empty: Story = {
    args: { viewKey: 'overview-metrics-empty-story', items: [] },
}

const openEditor: NonNullable<Story['play']> = async ({ canvasElement, args }) => {
    // The modal reads the logic the component mounts, so opening it before the mount is lost.
    const logic = await waitFor(
        () => {
            const mounted = overviewMetricsLogic.findMounted({ viewKey: args.viewKey! })
            expect(mounted).toBeTruthy()
            return mounted!
        },
        { timeout: 5000 }
    )
    logic.actions.openEditor()
    await waitFor(() => expect(within(canvasElement.ownerDocument.body).getByRole('dialog')).toBeVisible(), {
        timeout: 5000,
    })
}

const modalTestOptions = {
    waitForSelector: '.LemonModal.ReactModal__Content--after-open',
    snapshotTargetSelector: '.LemonModal',
}

export const ConfigureMetricsNarrow: Story = {
    args: { viewKey: 'overview-metrics-configure-narrow-story' },
    play: openEditor,
    parameters: { testOptions: { ...modalTestOptions, viewport: { width: 520, height: 1024 } } },
}

export const ConfigureMetricsWithChanges: Story = {
    args: { viewKey: 'overview-metrics-configure-changes-story' },
    parameters: { testOptions: modalTestOptions },
    play: async (context) => {
        await openEditor(context)
        const dialog = within(context.canvasElement.ownerDocument.body).getByRole('dialog')
        await userEvent.click(within(dialog).getByRole('button', { name: 'Move Clicks up' }))
        const platforms = within(within(dialog).getByRole('region', { name: 'Ad platforms' }))
        await userEvent.click(platforms.getByText('Impressions', { exact: true }))
        await userEvent.click(platforms.getByText('CTR', { exact: true }))
        await userEvent.click(
            within(within(dialog).getByRole('region', { name: 'PostHog' })).getByText('Trial started', {
                exact: true,
            })
        )
        const applyButton = within(dialog).getByRole('button', { name: 'Apply' })
        await expect(applyButton).toBeEnabled()
        const content = dialog.querySelector<HTMLElement>('.LemonModal__content')!
        // The last interaction focuses a control below the fold and scrolls the modal.
        ;(dialog.ownerDocument.activeElement as HTMLElement | null)?.blur()
        content.scrollTo({ top: 0, behavior: 'instant' })
        await waitFor(() => expect(content.scrollTop).toBe(0))
    },
}
