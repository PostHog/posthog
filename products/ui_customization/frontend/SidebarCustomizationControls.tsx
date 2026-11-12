import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconSparkles } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { autoRunMaxPrompt } from 'scenes/max/maxPrompt'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { SidebarCustomizationProps, sidebarCustomizationLogic } from './sidebarCustomizationLogic'

export interface SidebarCustomizationControlsProps extends SidebarCustomizationProps {
    customizePrompt: string
    customizeEvent: string
    dataAttrPrefix: string
}

export function SidebarCustomizationControls(props: SidebarCustomizationControlsProps): JSX.Element | null {
    const logic = sidebarCustomizationLogic(props)
    const { sidebarCustomizationEnabled, sidebarLayout, sidebarCustomized, sidebarLoading } = useValues(logic)
    const { resetSidebar } = useActions(logic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    // Only the PostHog AI that runs in a sandbox has the tools that save a layout.
    const canCustomize = !!featureFlags[FEATURE_FLAGS.PHAI_SANDBOX_MODE]

    if (!sidebarCustomizationEnabled || (!canCustomize && !sidebarCustomized)) {
        return null
    }
    return (
        <div className="mt-2 flex flex-col gap-px border-t border-border py-2">
            {canCustomize && (
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                size="row"
                                left
                                className="text-muted-foreground"
                                onClick={() => {
                                    posthog.capture(props.customizeEvent, { customized: sidebarCustomized })
                                    // The side panel keeps the sidebar in view while PostHog AI changes it.
                                    openSidePanel(SidePanelTab.Max, autoRunMaxPrompt(props.customizePrompt))
                                }}
                                data-attr={`${props.dataAttrPrefix}-customize`}
                            />
                        }
                    >
                        <IconSparkles />
                        Personalize with PostHog AI
                    </TooltipTrigger>
                    <TooltipContent side="right">GenUI, so hot right now</TooltipContent>
                </Tooltip>
            )}
            {sidebarCustomized && (
                <Button
                    size="row"
                    left
                    className="text-muted-foreground"
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
