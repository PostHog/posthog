import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { StatusIndicator } from '../../../components/Indicators'

export const IssueStatusSelect = ({
    status,
    onChange,
}: {
    status: ErrorTrackingIssue['status']
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element => {
    return (
        <ScenePanelLabel title="Status">
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive fullWidth className="flex justify-between" variant="panel" menuItem>
                        <StatusIndicator status={status} withTooltip={true} />
                        <DropdownMenuOpenIndicator />
                    </ButtonPrimitive>
                </DropdownMenuTrigger>

                <DropdownMenuContent loop matchTriggerWidth>
                    <DropdownMenuGroup>
                        {status === 'active' ? (
                            <>
                                <DropdownMenuItem asChild>
                                    <ButtonPrimitive menuItem onClick={() => onChange('resolved')}>
                                        <StatusIndicator status="resolved" intent />
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                                <DropdownMenuItem asChild>
                                    <ButtonPrimitive menuItem onClick={() => onChange('suppressed')}>
                                        <StatusIndicator status="suppressed" intent />
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                            </>
                        ) : (
                            <DropdownMenuItem asChild>
                                <ButtonPrimitive menuItem onClick={() => onChange('active')}>
                                    <StatusIndicator status="active" intent />
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        </ScenePanelLabel>
    )
}
