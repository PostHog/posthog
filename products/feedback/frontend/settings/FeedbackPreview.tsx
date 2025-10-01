import { useValues } from 'kea'
import { useState } from 'react'

import { IconUpload } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { feedbackGeneralSettingsLogic } from './feedbackGeneralSettingsLogic'

export function FeedbackPreview(): JSX.Element {
    const { feedbackCategories } = useValues(feedbackGeneralSettingsLogic)
    const [selectedCategory, setSelectedCategory] = useState<string>(feedbackCategories[0] || '')

    return (
        <div className="border rounded-lg bg-surface-primary shadow-sm">
            {feedbackCategories.length > 0 && (
                <div className="flex gap-1 p-2 border-b bg-surface-light">
                    <LemonSegmentedButton
                        value={selectedCategory}
                        onChange={(value) => setSelectedCategory(value)}
                        options={feedbackCategories.map((category) => ({
                            value: category,
                            label: <span className="capitalize">{category}</span>,
                        }))}
                        size="small"
                        fullWidth
                    />
                </div>
            )}

            <div className="p-4 flex flex-col gap-3">
                <textarea
                    placeholder="Type your feedback here..."
                    className="w-full min-h-24 p-3 border rounded resize-none focus:outline-none focus:ring-2 focus:ring-primary bg-surface-primary"
                    disabled
                />

                <div className="flex gap-2">
                    <LemonButton type="secondary" icon={<IconUpload />} fullWidth disabledReason="Preview only">
                        Upload screenshot
                    </LemonButton>
                </div>

                <LemonButton type="primary" fullWidth disabledReason="Preview only">
                    Submit feedback
                </LemonButton>
            </div>
        </div>
    )
}
