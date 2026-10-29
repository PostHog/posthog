import clsx from 'clsx'
import { RefObject } from 'react'

import { IconChevronDown, IconSend } from '@posthog/icons'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'

import { messageAudienceAccessDisabledReason } from 'products/workflows/frontend/MessageAudience/messageAudience'

import { IssueEmailMenuItems } from './IssueEmailMenuItems'
import { IssueAffectedBroadcastLogicProps } from './ScenePanel/issueAffectedBroadcastLogic'
import { IssueAffectedBroadcastModal } from './ScenePanel/IssueAffectedBroadcastModal'

export interface IssueEmailMenuProps extends IssueAffectedBroadcastLogicProps {
    /** Hides the button on a narrow scene, where the header menu next to it carries the same items. */
    collapseWhenNarrow?: boolean
    wrapperRef?: RefObject<HTMLDivElement>
}

export function IssueEmailMenu({ collapseWhenNarrow, wrapperRef, ...props }: IssueEmailMenuProps): JSX.Element {
    const accessDisabledReason = messageAudienceAccessDisabledReason()

    return (
        <>
            <div ref={wrapperRef} className={clsx(collapseWhenNarrow ? 'hidden @6xl/main-content:flex' : 'flex')}>
                {accessDisabledReason ? (
                    <Tooltip>
                        <TooltipTrigger render={<Button variant="outline" disabled />}>
                            <IconSend />
                            Email users
                        </TooltipTrigger>
                        <TooltipContent>{accessDisabledReason}</TooltipContent>
                    </Tooltip>
                ) : (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={<Button variant="outline" data-attr="error-tracking-issue-email-menu" />}
                        >
                            <IconSend />
                            Email users
                            <IconChevronDown />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-auto min-w-56">
                            <IssueEmailMenuItems {...props} />
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
            </div>
            <IssueAffectedBroadcastModal {...props} />
        </>
    )
}
