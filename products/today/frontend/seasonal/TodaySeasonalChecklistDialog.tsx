import { useActions, useValues } from 'kea'
import { Fragment, forwardRef, useCallback, useState } from 'react'

import {
    Badge,
    Button,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaDescription,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    ItemGroup,
    ItemSeparator,
    Text,
} from '@posthog/quill'

import type { SeasonalChecklist } from './seasonalChecklist'
import { todaySeasonalChecklistLogic } from './todaySeasonalChecklistLogic'
import { TodaySeasonalChecklistRow } from './TodaySeasonalChecklistRow'
import { TodaySeasonalLights } from './TodaySeasonalLights'
import { TodaySeasonalProgress } from './TodaySeasonalProgress'

export const TodaySeasonalChecklistDialog = forwardRef<HTMLDivElement, { checklist: SeasonalChecklist }>(
    function TodaySeasonalChecklistDialog({ checklist }, ref): JSX.Element {
        const { isOpen, allDone, doneCount, items } = useValues(todaySeasonalChecklistLogic)
        const { closeChecklist, dismissChecklist } = useActions(todaySeasonalChecklistLogic)
        const [introHeight, setIntroHeight] = useState(0)
        const measureIntro = useCallback((element: HTMLDivElement | null): void => {
            if (element) {
                setIntroHeight((height) => Math.max(height, element.offsetHeight))
            }
        }, [])

        return (
            <Credenza open={isOpen} onOpenChange={(open: boolean) => !open && closeChecklist()}>
                <CredenzaContent
                    ref={ref}
                    className="TodaySeasonalChecklist sm:max-w-160"
                    data-attr="today-seasonal-checklist"
                >
                    <CredenzaHeader className="relative gap-2 pt-8">
                        {checklist.lights ? <TodaySeasonalLights /> : null}
                        <div ref={measureIntro} style={{ minHeight: introHeight }}>
                            <CredenzaTitle className="flex items-center gap-2">
                                <span>{allDone ? checklist.doneTitle : checklist.title}</span>
                                {checklist.badge ? <Badge variant="warning">{checklist.badge}</Badge> : null}
                            </CredenzaTitle>
                            <CredenzaDescription>
                                {allDone ? checklist.doneDescription : checklist.description}
                            </CredenzaDescription>
                            {checklist.reason && !allDone ? (
                                <Text size="xs" className="m-0 text-subtle-foreground">
                                    {checklist.reason}
                                </Text>
                            ) : null}
                        </div>
                        <TodaySeasonalProgress done={doneCount} total={items.length} />
                    </CredenzaHeader>
                    <CredenzaBody>
                        <ItemGroup combined>
                            {items.map((item, index) => (
                                <Fragment key={item.key}>
                                    {index > 0 ? <ItemSeparator className="my-0" /> : null}
                                    <TodaySeasonalChecklistRow item={item} />
                                </Fragment>
                            ))}
                        </ItemGroup>
                    </CredenzaBody>
                    <CredenzaFooter>
                        <Button
                            variant="outline"
                            onClick={dismissChecklist}
                            data-attr="today-seasonal-checklist-dismiss"
                        >
                            Don’t show again
                        </Button>
                        {allDone ? (
                            <Button
                                variant="primary"
                                onClick={closeChecklist}
                                data-attr="today-seasonal-checklist-done"
                            >
                                Done
                            </Button>
                        ) : null}
                    </CredenzaFooter>
                </CredenzaContent>
            </Credenza>
        )
    }
)
