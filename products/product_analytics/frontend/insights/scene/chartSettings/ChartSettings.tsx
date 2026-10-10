import { useActions, useValues } from 'kea'

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { ChartGoalLines } from './ChartGoalLines'
import { ChartSettingRow } from './ChartSettingRow'
import { chartSettingsLogic } from './chartSettingsLogic'

/**
 * The display settings that apply to the insight's current chart type, one closed section for each group.
 * Shows nothing for an insight that is not a trend.
 */
export function ChartSettings({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const logic = chartSettingsLogic(insightProps)
    const { groups, goalLinesSupported } = useValues(logic)
    const { changeSetting } = useActions(logic)

    if (!groups.length && !goalLinesSupported) {
        return null
    }

    return (
        <div data-quill className="flex w-full flex-col gap-2" data-attr="quill-insight-chart-settings">
            <Text size="xs" variant="muted">
                Chart settings
            </Text>
            <Accordion>
                {groups.map((group) => (
                    <AccordionItem key={group.key} value={group.key}>
                        <AccordionTrigger data-attr={`quill-insight-chart-settings-section-${group.key}`}>
                            {group.title}
                        </AccordionTrigger>
                        <AccordionContent className="flex flex-col gap-2 pt-1">
                            {group.settings.map((setting) => (
                                <ChartSettingRow
                                    key={setting.id}
                                    setting={setting}
                                    onChange={(value) => changeSetting(setting.id, value)}
                                />
                            ))}
                        </AccordionContent>
                    </AccordionItem>
                ))}
                {goalLinesSupported && (
                    <AccordionItem value="goal-lines">
                        <AccordionTrigger data-attr="quill-insight-chart-settings-section-goal-lines">
                            Goal lines
                        </AccordionTrigger>
                        <AccordionContent className="flex flex-col gap-2 pt-1">
                            <ChartGoalLines insightProps={insightProps} />
                        </AccordionContent>
                    </AccordionItem>
                )}
            </Accordion>
        </div>
    )
}
