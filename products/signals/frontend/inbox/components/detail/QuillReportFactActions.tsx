import { useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { ReportDetailAction } from './ReportDetailActions'
import { QuillReportClaim } from './useQuillReportClaim'

const INLINE_ACTION_LIMIT = 2
// The owner in the fact line holds the take-over action, so the action list does not repeat it.
const OWNER_ACTION_KEYS = ['takeover']

export function QuillReportFactActions({
    claim,
    actions,
}: {
    claim: QuillReportClaim
    actions: ReportDetailAction[]
}): JSX.Element {
    const { phoneLayout } = useValues(todayShellLogic)
    const listed = actions.filter((action) => !OWNER_ACTION_KEYS.includes(action.key))
    const inlineActions = phoneLayout ? [] : listed.slice(0, INLINE_ACTION_LIMIT)
    const menuActions = phoneLayout ? listed : listed.slice(INLINE_ACTION_LIMIT)
    // A phone has no room for the Claim button, so the claim actions join the other actions in the menu.
    const claimMenuItems = phoneLayout
        ? [
              claim.canClaim && { key: 'claim', label: 'Claim', onClick: claim.claim },
              claim.canUnclaim && { key: 'unclaim', label: 'Unclaim', onClick: claim.unclaim },
              claim.canTakeOver && { key: 'takeover', label: 'Take over', onClick: claim.takeOver },
          ].filter((item) => !!item)
        : []

    return (
        <div className="-mx-2 flex shrink-0 items-center gap-0.5 self-start">
            {!phoneLayout && claim.canClaim && (
                <Button
                    size="sm"
                    variant="link-muted"
                    loading={claim.saving}
                    onClick={claim.claim}
                    tooltip="Claim this report (U)"
                    data-attr="inbox-report-claim"
                >
                    Claim
                </Button>
            )}
            {inlineActions.map((action) => (
                <Button
                    key={action.key}
                    size="sm"
                    variant={action.primary ? 'outline' : 'link-muted'}
                    loading={action.loading}
                    // A disabled action explains only why it is unavailable, not what it would do.
                    tooltip={action.disabledReason ? undefined : action.tooltip}
                    disabledReason={action.disabledReason}
                    onClick={action.onClick}
                    data-attr={`inbox-report-action-${action.key}`}
                >
                    {action.label}
                </Button>
            ))}
            {menuActions.length + claimMenuItems.length > 0 && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon-sm"
                                variant="link-muted"
                                aria-label="More actions"
                                tooltip="More actions"
                                data-attr="inbox-report-more-actions"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        {claimMenuItems.map((item) => (
                            <DropdownMenuItem
                                key={item.key}
                                disabledReason={claim.saving ? 'Working…' : undefined}
                                onClick={item.onClick}
                                data-attr={`inbox-report-action-${item.key}`}
                            >
                                {item.label}
                            </DropdownMenuItem>
                        ))}
                        {menuActions.map((action) => (
                            <DropdownMenuItem
                                key={action.key}
                                disabledReason={action.loading ? 'Working…' : action.disabledReason}
                                onClick={action.onClick}
                                data-attr={`inbox-report-action-${action.key}`}
                            >
                                {action.icon}
                                {action.label}
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    )
}
