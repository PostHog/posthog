import type { Meta, StoryObj } from '@storybook/react'

import { NotebookWidgetTrustControls, type NotebookWidgetTrustControlsProps } from './NotebookWidgetTrustControls'

type Story = StoryObj<NotebookWidgetTrustControlsProps>

const meta: Meta<NotebookWidgetTrustControlsProps> = {
    title: 'Products/Notebooks/Notebook widget trust controls',
    component: NotebookWidgetTrustControls,
    args: {
        buildHash: 'a'.repeat(64),
        isEditable: true,
        securityReview: {
            severity: 'high',
            summary: 'The widget may send notebook data to another window.',
            findings: [
                {
                    severity: 'high',
                    title: 'Notebook data may leave the preview',
                    details: 'The source sends rows to the parent window without using the approved bridge.',
                },
            ],
            model: 'claude-haiku-4-5',
            review_version: '1',
            reviewed_at: '2026-08-31T10:00:00Z',
        },
        onRun: () => undefined,
        onViewSource: () => undefined,
    },
}

export default meta

export const Gate: Story = {
    args: { variant: 'gate' },
}

export const Toolbar: Story = {
    args: {
        variant: 'toolbar',
        securityReview: {
            severity: 'none',
            summary: 'No security issues found.',
            findings: [],
            model: 'claude-haiku-4-5',
            review_version: '1',
            reviewed_at: '2026-08-31T10:00:00Z',
        },
    },
}

export const MissingBuildHash: Story = {
    args: { buildHash: null, securityReview: null, variant: 'gate' },
}
