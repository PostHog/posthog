import { useActions, useValues } from 'kea'

import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { MenuChoiceItem } from '../MenuChoiceItem'
import { EditableWord } from './EditableWord'
import { insightSentenceLogic } from './insightSentenceLogic'

const USERS = 'users'

export function SentenceFunnelActor({
    insightProps,
    label,
}: {
    insightProps: InsightLogicProps
    label: string
}): JSX.Element {
    const { funnelsQuery, funnelActorOptions } = useValues(insightSentenceLogic(insightProps))
    const { changeFunnelActor } = useActions(insightSentenceLogic(insightProps))
    const groupTypeIndex = funnelsQuery?.aggregation_group_type_index ?? null
    // A funnel counted by a SQL expression matches no option, so none shows as chosen.
    const value = funnelsQuery?.funnelsFilter?.funnelAggregateByHogQL
        ? ''
        : groupTypeIndex === null
          ? USERS
          : String(groupTypeIndex)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<EditableWord color="purple" data-attr="quill-insight-sentence-funnel-actor" />}
            >
                {label}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56">
                <DropdownMenuRadioGroup
                    value={value}
                    onValueChange={(next: string) => changeFunnelActor(next === USERS ? null : Number(next))}
                >
                    {funnelActorOptions.map((option) => (
                        <MenuChoiceItem
                            key={option.groupTypeIndex ?? USERS}
                            value={option.groupTypeIndex === null ? USERS : String(option.groupTypeIndex)}
                        >
                            {option.label}
                        </MenuChoiceItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
