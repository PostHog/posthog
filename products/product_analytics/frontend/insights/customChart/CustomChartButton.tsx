import { useActions } from 'kea'
import posthog from 'posthog-js'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { CustomChartSettings } from '~/queries/schema/schema-general'

import { CustomChartChangeModal } from './CustomChartChangeModal'
import { CustomChartData } from './customChartData'
import { CUSTOM_CHART_EVENTS } from './customChartEvents'
import { customChartLogic } from './customChartLogic'
import { CustomChartModal } from './CustomChartModal'
import { customChartModalLogic } from './customChartModalLogic'

export interface CustomChartButtonProps {
    /** Keys the create dialog to one insight view. */
    logicKey: string
    customChart: CustomChartSettings | null | undefined
    insightName: string
    data: CustomChartData | null
    onChange: (customChart: CustomChartSettings | null) => void
    disabledReason?: string | null
}

export function CustomChartButton({
    logicKey,
    customChart,
    insightName,
    data,
    onChange,
    disabledReason,
}: CustomChartButtonProps): JSX.Element {
    const modalLogicProps = {
        key: logicKey,
        insightName,
        data,
        onCreated: (canvasId: string) => onChange({ canvasId }),
    }
    const { openModal } = useActions(customChartModalLogic(modalLogicProps))

    if (!customChart) {
        return (
            <>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconSparkles />}
                    onClick={openModal}
                    disabledReason={disabledReason}
                    data-attr="custom-chart-open"
                >
                    Custom chart
                </LemonButton>
                <CustomChartModal logicProps={modalLogicProps} />
            </>
        )
    }

    return (
        <ActiveCustomChartButton canvasId={customChart.canvasId} onChange={onChange} disabledReason={disabledReason} />
    )
}

function ActiveCustomChartButton({
    canvasId,
    onChange,
    disabledReason,
}: {
    canvasId: string
    onChange: (customChart: CustomChartSettings | null) => void
    disabledReason?: string | null
}): JSX.Element {
    const { openChangeModal } = useActions(customChartLogic({ canvasId }))

    return (
        <>
            <LemonMenu
                items={[
                    { label: 'Change the chart…', onClick: openChangeModal, 'data-attr': 'custom-chart-change' },
                    { label: 'Open its canvas', to: urls.canvasDetail(canvasId), 'data-attr': 'custom-chart-canvas' },
                    {
                        label: 'Use the built-in chart',
                        onClick: () => {
                            posthog.capture(CUSTOM_CHART_EVENTS.removed, { canvas_id: canvasId })
                            onChange(null)
                        },
                        'data-attr': 'custom-chart-remove',
                    },
                ]}
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    active
                    icon={<IconSparkles />}
                    disabledReason={disabledReason}
                    data-attr="custom-chart-menu"
                >
                    Custom chart
                </LemonButton>
            </LemonMenu>
            <CustomChartChangeModal canvasId={canvasId} />
        </>
    )
}
