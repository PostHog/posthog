import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { debugLogsLogic } from '../logics/debugLogsLogic'

export interface DebugLogsMenuProps {
    /**
     * `lemon` matches the small secondary buttons in the main `/ai` header; `primitive` matches the
     * icon-only chrome in the side-panel header. Mirrors `PhaiViewToggle`, which sits beside it.
     */
    variant?: 'lemon' | 'primitive'
}

/**
 * Overflow menu carrying the debug-logs preference for hosts that have no scene chrome to hang it on.
 * The `/tasks` runner uses the scene menu bar and scene panel instead; this is the form the PostHog AI
 * scene and side panel use, where the only surface is a hand-rolled header.
 *
 * Renders nothing unless the current user may control debug logs, so a non-staff viewer never sees an
 * empty kebab. Debug rows exist only on the sandbox runtime, so the host decides whether the thread
 * below it can show them at all - keeping this component free of any conversation or runtime knowledge.
 */
export function DebugLogsMenu({ variant = 'lemon' }: DebugLogsMenuProps): JSX.Element | null {
    const { canControlDebugLogs, debugLogsEnabled } = useValues(debugLogsLogic)
    const { setDebugLogsEnabled } = useActions(debugLogsLogic)

    if (!canControlDebugLogs) {
        return null
    }

    return (
        <LemonMenu
            // Keep the menu open when the switch flips, so the debug rows appearing behind it are visible
            // straight away. Clicking outside closes it.
            closeOnClickInside={false}
            items={[
                {
                    custom: true,
                    label: () => (
                        <LemonSwitch
                            data-attr="run-toggle-debug-logs"
                            className="px-2 py-1"
                            checked={debugLogsEnabled}
                            onChange={setDebugLogsEnabled}
                            fullWidth
                            label="Show debug logs"
                        />
                    ),
                },
            ]}
        >
            {variant === 'primitive' ? (
                <ButtonPrimitive
                    iconOnly
                    tooltip="Staff options"
                    tooltipPlacement="bottom-end"
                    data-attr="run-staff-menu"
                >
                    <IconEllipsis className="text-tertiary size-3 group-hover:text-primary z-10" />
                </ButtonPrimitive>
            ) : (
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconEllipsis />}
                    tooltip="Staff options"
                    data-attr="run-staff-menu"
                />
            )}
        </LemonMenu>
    )
}
