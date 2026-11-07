import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SidebarCustomizationProps, sidebarCustomizationLogic } from './sidebarCustomizationLogic'

export interface SidebarCustomizationControlsProps extends SidebarCustomizationProps {
    customizeUrl: string
    customizeEvent: string
    dataAttrPrefix: string
}

export function SidebarCustomizationControls(props: SidebarCustomizationControlsProps): JSX.Element | null {
    const logic = sidebarCustomizationLogic(props)
    const { sidebarCustomizationEnabled, sidebarLayout, sidebarCustomized, sidebarLoading } = useValues(logic)
    const { resetSidebar } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    // Only the PostHog AI that runs in a sandbox has the tools that save a layout.
    const canCustomize = !!featureFlags[FEATURE_FLAGS.PHAI_SANDBOX_MODE]

    if (!sidebarCustomizationEnabled || (!canCustomize && !sidebarCustomized)) {
        return null
    }
    return (
        <div className="mt-2 flex flex-wrap items-center gap-1 border-t border-border pt-2">
            {canCustomize && (
                <Button
                    size="sm"
                    variant="link-muted"
                    nativeButton={false}
                    render={<LinkPrimitive to={props.customizeUrl} />}
                    onClick={() => posthog.capture(props.customizeEvent, { customized: sidebarCustomized })}
                    data-attr={`${props.dataAttrPrefix}-customize`}
                >
                    <IconSparkles />
                    Customize with PostHog AI
                </Button>
            )}
            {sidebarCustomized && (
                <Button
                    size="sm"
                    variant="link-muted"
                    loading={sidebarLoading}
                    onClick={() => resetSidebar(sidebarLayout)}
                    data-attr={`${props.dataAttrPrefix}-reset`}
                >
                    Reset to default
                </Button>
            )}
        </div>
    )
}
