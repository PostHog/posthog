import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import type { ProductBriefListApi } from './generated/api.schemas'
import { ProductBriefStatusEnumApi } from './generated/api.schemas'
import { pulseLogic } from './pulseLogic'

// Exhaustive over the enum so a new backend status fails compilation here instead of rendering unstyled.
export const STATUS_TAG_TYPES: Record<ProductBriefStatusEnumApi, LemonTagType> = {
    [ProductBriefStatusEnumApi.Generating]: 'warning',
    [ProductBriefStatusEnumApi.Ready]: 'success',
    [ProductBriefStatusEnumApi.Quiet]: 'default',
    [ProductBriefStatusEnumApi.Failed]: 'danger',
}

export function BriefHistoryList({ briefs }: { briefs: ProductBriefListApi[] }): JSX.Element {
    const { selectedBriefId, briefsHasMore } = useValues(pulseLogic)
    const { selectBrief } = useActions(pulseLogic)

    return (
        <div className="w-72 shrink-0 flex flex-col gap-1">
            {briefs.map((brief) => (
                <LemonButton
                    key={brief.id}
                    fullWidth
                    active={brief.id === selectedBriefId}
                    onClick={() => selectBrief(brief.id)}
                >
                    <div className="flex items-center justify-between gap-2 w-full">
                        <TZLabel time={brief.created_at} />
                        <LemonTag type={STATUS_TAG_TYPES[brief.status]}>{brief.status}</LemonTag>
                    </div>
                </LemonButton>
            ))}
            {briefsHasMore && (
                // TODO: paginate the brief history. Surfaced here rather than hidden in code so we
                // address it before rolling Pulse out more widely.
                <div className="text-muted text-xs px-2 py-1">
                    Showing the most recent briefs only. Pagination is coming soon.
                </div>
            )}
        </div>
    )
}
