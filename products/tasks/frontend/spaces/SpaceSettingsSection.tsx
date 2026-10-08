import { ReactNode } from 'react'

import { Text } from '@posthog/quill'

export interface SpaceSettingsSectionProps {
    label: string
    description?: ReactNode
    /** Shown at the end of the label row, like a count or an add button. */
    action?: ReactNode
    children: ReactNode
}

/** A labeled block of the space settings page, modeled on PostHog Desktop's `SettingsSection`. */
export function SpaceSettingsSection({ label, description, action, children }: SpaceSettingsSectionProps): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-0.5">
                <div className="flex min-w-0 flex-col gap-0.5">
                    {/* A heading role rather than an h3, because the app's global h3 margin would push the description down. */}
                    <Text size="xs" weight="semibold" role="heading" aria-level={3}>
                        {label}
                    </Text>
                    {description && (
                        <Text size="xs" variant="muted">
                            {description}
                        </Text>
                    )}
                </div>
                {action && <div className="flex shrink-0 items-center">{action}</div>}
            </div>
            {children}
        </section>
    )
}
