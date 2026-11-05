import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown } from '@posthog/lemon-ui'

import type { HighlightFeedCategoryEnumApi } from '../../generated/api.schemas'
import { FEED_CATEGORIES, highlightFeedLogic } from '../highlightFeedLogic'

const CATEGORY_COPY: Record<HighlightFeedCategoryEnumApi, { label: string; description: string }> = {
    failure: { label: 'Failures', description: 'Errors, failed requests, clicks that did nothing, dead ends.' },
    struggle: { label: 'Struggles', description: 'Repeated attempts, rage clicks, abandoned forms, workarounds.' },
    revenue: {
        label: 'Payment or checkout problems',
        description: 'Failed payments, cancellations and downgrades, usage limits.',
    },
}

export function HighlightFeedCustomizeButton(): JSX.Element {
    const { categories } = useValues(highlightFeedLogic)
    const { setCategories } = useActions(highlightFeedLogic)
    const customized = categories.length < FEED_CATEGORIES.length
    return (
        <LemonDropdown
            closeOnClickInside={false}
            placement="bottom-end"
            overlay={
                <div className="flex w-80 flex-col gap-3 p-2" data-attr="vision-highlight-feed-customize-menu">
                    <div className="text-xs font-semibold uppercase text-secondary">Include sessions with</div>
                    {FEED_CATEGORIES.map((category) => {
                        const checked = categories.includes(category)
                        return (
                            <div key={category} className="flex flex-col gap-0.5">
                                <LemonCheckbox
                                    label={<span className="font-medium">{CATEGORY_COPY[category].label}</span>}
                                    checked={checked}
                                    disabledReason={
                                        checked && categories.length === 1 ? 'Keep at least one kind on' : undefined
                                    }
                                    onChange={(value) =>
                                        setCategories(
                                            value ? [...categories, category] : categories.filter((c) => c !== category)
                                        )
                                    }
                                    data-attr={`vision-highlight-feed-category-${category}`}
                                />
                                <span className="pl-6 text-xs text-secondary">
                                    {CATEGORY_COPY[category].description}
                                </span>
                            </div>
                        )
                    })}
                </div>
            }
        >
            <LemonButton
                size="small"
                type="tertiary"
                icon={
                    <span className="relative flex">
                        <IconGear />
                        {customized && (
                            <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-accent" aria-hidden />
                        )}
                    </span>
                }
                tooltip={customized ? 'Customize feed (some kinds are hidden)' : 'Customize feed'}
                aria-label="Customize feed"
                data-attr="vision-highlight-feed-customize"
            />
        </LemonDropdown>
    )
}
