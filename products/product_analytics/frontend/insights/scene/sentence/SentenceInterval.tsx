import { useActions, useValues } from 'kea'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    Text,
} from '@posthog/quill'

import type { InsightLogicProps, IntervalType } from '~/types'

import { EditableWord } from './EditableWord'
import { insightSentenceLogic } from './insightSentenceLogic'

export function SentenceInterval({
    insightProps,
    label,
}: {
    insightProps: InsightLogicProps
    label: string
}): JSX.Element {
    const { enabledIntervals, trendsQuery, overriddenSlots } = useValues(insightSentenceLogic(insightProps))
    const { changeInterval } = useActions(insightSentenceLogic(insightProps))

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <EditableWord
                        color="orange"
                        overridden={overriddenSlots.includes('interval')}
                        data-attr="quill-insight-sentence-interval"
                    />
                }
            >
                {label}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56">
                <DropdownMenuRadioGroup
                    value={trendsQuery?.interval ?? 'day'}
                    onValueChange={(value: string) => changeInterval(value as IntervalType)}
                >
                    {Object.entries(enabledIntervals)
                        .filter(([, option]) => !option.hidden)
                        .map(([value, option]) => (
                            <DropdownMenuRadioItem key={value} value={value} disabled={!!option.disabledReason}>
                                <span>{option.label}</span>
                                {option.disabledReason && (
                                    <Text size="xs" variant="muted" render={<span />}>
                                        {option.disabledReason}
                                    </Text>
                                )}
                            </DropdownMenuRadioItem>
                        ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
