import clsx from 'clsx'
import { useValues } from 'kea'
import { useState } from 'react'

import { IconUpload } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { feedbackGeneralSettingsLogic } from './feedbackGeneralSettingsLogic'

export function FeedbackPreview(): JSX.Element {
    const { feedbackTypes } = useValues(feedbackGeneralSettingsLogic)
    const [selectedType, setSelectedType] = useState<string | null>(feedbackTypes[0] || null)

    return (
        <div className="border rounded-lg bg-surface-primary shadow-lg">
            <div className="flex gap-1 p-2 border-b bg-surface-light">
                {feedbackTypes.map((type) => (
                    <button
                        key={type}
                        onClick={() => setSelectedType(type)}
                        className={clsx(
                            'p-1 rounded text-sm font-medium transition-colors capitalize',
                            selectedType === type
                                ? 'bg-primary text-primary-content'
                                : 'bg-surface-primary text-default hover:bg-surface-secondary'
                        )}
                    >
                        {type}
                    </button>
                ))}
            </div>

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
