import type { Meta, StoryObj } from '@storybook/react'

import { BRAND_MARKS, type BrandMarkName, type IconMarkName } from '../brandMarks'
import { BrandMark } from './BrandMark'

const ICON_MARK_NAMES: IconMarkName[] = ['PostHog', 'Unbranded model', 'Other harnesses', 'Unidentified client']
const MARK_NAMES: BrandMarkName[] = [...(Object.keys(BRAND_MARKS) as (keyof typeof BRAND_MARKS)[]), ...ICON_MARK_NAMES]

const meta: Meta<typeof BrandMark> = {
    title: 'Products/MCP Analytics/Brand marks',
    component: BrandMark,
}
export default meta

type Story = StoryObj<typeof BrandMark>

export const AllMarks: Story = {
    render: () => (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-x-6 gap-y-3 p-4 text-sm">
            {MARK_NAMES.map((name) => (
                <div key={name} className="flex items-center gap-2">
                    <BrandMark name={name} label={name} className="size-8" />
                    <BrandMark name={name} label={name} />
                    <span className="truncate">{name}</span>
                </div>
            ))}
        </div>
    ),
}
