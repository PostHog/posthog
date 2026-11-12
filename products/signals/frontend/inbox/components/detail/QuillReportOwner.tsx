import './QuillReportDetail.scss'

import { ProfilePicture } from '@posthog/lemon-ui'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
    DropdownMenuTrigger,
    KbdGroup,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { isMac } from 'lib/utils/dom'

import { QuillReportClaim } from './useQuillReportClaim'

const COMMAND_KEY = isMac() ? '⌘' : 'Ctrl'

export function QuillReportOwner({ claim }: { claim: QuillReportClaim }): JSX.Element {
    const label = (
        <>
            {claim.holder && (
                <span className={claim.ownerKind.endsWith('agent') ? 'QuillReportOwner__agent' : undefined}>
                    <ProfilePicture user={claim.holder} size="sm" />
                </span>
            )}
            <span data-attr="inbox-report-claim-pill">{claim.ownerLabel}</span>
        </>
    )
    if (!claim.canUnclaim && !claim.canTakeOver) {
        return <span className="inline-flex items-center gap-1.5">{label}</span>
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="inline"
                        variant="link-muted"
                        className="QuillReportFact inline-flex items-center gap-1.5"
                        loading={claim.saving}
                        data-attr="inbox-report-owner"
                    />
                }
            >
                {label}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                {claim.claimedAt && (
                    <>
                        <Text
                            size="xs"
                            variant="muted"
                            render={<div />}
                            className="flex items-center gap-1 px-2 py-1.5"
                        >
                            <span>{claim.canUnclaim ? 'You claimed this report' : claim.ownerLabel}</span>
                            <TZLabel time={claim.claimedAt} />
                        </Text>
                        <DropdownMenuSeparator />
                    </>
                )}
                {claim.canUnclaim ? (
                    <DropdownMenuItem onClick={claim.unclaim} data-attr="inbox-report-unclaim">
                        Unclaim
                        <KbdGroup className="ms-auto">
                            <DropdownMenuShortcut>{COMMAND_KEY}</DropdownMenuShortcut>
                            <DropdownMenuShortcut>U</DropdownMenuShortcut>
                        </KbdGroup>
                    </DropdownMenuItem>
                ) : (
                    <DropdownMenuItem onClick={claim.takeOver} data-attr="inbox-report-action-takeover">
                        Take over
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
