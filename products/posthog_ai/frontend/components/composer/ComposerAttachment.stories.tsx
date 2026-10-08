import type { Meta, StoryObj } from '@storybook/react'

import { QuillComposerAttachment } from '../quill/QuillComposerAttachment'
import { ComposerAttachment } from './ComposerAttachment'

const files = [
    new File(['Quarter,Total\nQ1,42'], 'quarterly-report.csv'),
    new File(['{}'], 'settings.json'),
    new File(['Notes'], 'notes-with-a-long-name-to-check-the-tooltip.md'),
    new File(['Text'], 'README'),
    new File(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#f9bd2b"/><circle cx="32" cy="32" r="18" fill="#1d4aff"/></svg>',
        ],
        'diagram.svg',
        { type: 'image/svg+xml' }
    ),
]

const meta: Meta<typeof ComposerAttachment> = {
    title: 'Products/PostHog AI/Composer attachments',
    component: ComposerAttachment,
    args: { uploading: false, onRemove: () => {} },
    render: (args) => (
        <div className="flex flex-wrap items-center gap-2 p-4">
            {files.map((file) => (
                <ComposerAttachment key={file.name} {...args} file={file} />
            ))}
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof meta>

export const Lemon: Story = {}

export const Quill: Story = {
    render: (args) => (
        <div data-quill className="flex flex-wrap items-center gap-2 p-4">
            {files.map((file) => (
                <QuillComposerAttachment key={file.name} {...args} file={file} />
            ))}
        </div>
    ),
}

export const Uploading: Story = { args: { uploading: true } }

export const QuillUploading: Story = { ...Quill, args: { uploading: true } }
