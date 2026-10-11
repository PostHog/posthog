import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    ItemContent,
    ItemDescription,
    ItemTitle,
} from '@posthog/quill'

import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/insightTypesMetadata'

import { InsightType } from '~/types'
import type { InsightLogicProps } from '~/types'

import { MenuChoiceItem } from './MenuChoiceItem'

const KINDS = [
    InsightType.TRENDS,
    InsightType.FUNNELS,
    InsightType.RETENTION,
    InsightType.PATHS,
    InsightType.STICKINESS,
    InsightType.LIFECYCLE,
]

const ROW_CLASSES = 'h-auto items-start py-1.5 whitespace-normal [&>svg]:mt-1.5'

function KindRow({ kind }: { kind: InsightType }): JSX.Element {
    const { name, description, icon: Icon } = INSIGHT_TYPES_METADATA[kind]
    return (
        <>
            <Icon />
            <ItemContent variant="menuItem">
                <ItemTitle>{name}</ItemTitle>
                {description && <ItemDescription>{description}</ItemDescription>}
            </ItemContent>
        </>
    )
}

export function InsightKindMenu({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { activeView } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))

    if (!KINDS.includes(activeView)) {
        return null
    }

    const { name, icon: Icon } = INSIGHT_TYPES_METADATA[activeView]

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button variant="outline" size="sm" className="ms-1 shrink-0" data-attr="quill-insight-kind" />}
            >
                <Icon />
                {name}
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-w-96 min-w-80">
                <DropdownMenuRadioGroup
                    value={activeView}
                    onValueChange={(kind: InsightType) => {
                        if (kind !== activeView) {
                            setActiveView(kind)
                        }
                    }}
                >
                    {KINDS.map((kind) => (
                        <MenuChoiceItem
                            key={kind}
                            value={kind}
                            className={ROW_CLASSES}
                            data-attr={`quill-insight-kind-${kind.toLowerCase()}`}
                        >
                            <KindRow kind={kind} />
                        </MenuChoiceItem>
                    ))}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                {/* SQL has its own editor, so this item leaves the screen instead of changing it. */}
                <DropdownMenuItem
                    className={ROW_CLASSES}
                    onClick={() => setActiveView(InsightType.SQL)}
                    data-attr="quill-insight-kind-sql"
                >
                    <KindRow kind={InsightType.SQL} />
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
