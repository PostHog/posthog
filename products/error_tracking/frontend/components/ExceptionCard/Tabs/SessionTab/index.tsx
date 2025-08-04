import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveContentProps,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { SessionTimeline } from './SessionTimeline'
import { SessionRecording } from './SessionRecording'
import { SubHeader } from '../SubHeader'
import { BindLogic, useActions, useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { sessionTabLogic } from './sessionTabLogic'
import { match, P } from 'ts-pattern'
import { Spinner } from '@posthog/lemon-ui'
import { exceptionCardLogic } from '../../exceptionCardLogic'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

export interface SessionTabProps extends TabsPrimitiveContentProps {
    timestamp?: string
}

export function SessionTab({ timestamp, ...props }: SessionTabProps): JSX.Element {
    const { sessionId } = useValues(errorPropertiesLogic)
    const { loading, currentSessionTab } = useValues(exceptionCardLogic)
    const { setCurrentSessionTab } = useActions(exceptionCardLogic)

    return (
        <TabsPrimitiveContent {...props}>
            {match([loading, sessionId])
                .with([true, P.any], () => (
                    <div className="flex justify-center items-center h-[300px]">
                        <Spinner />
                    </div>
                ))
                .with([false, P.nullish], () => <NoSessionIdFound />)
                .with([false, P.string], ([_, sessionId]) => (
                    <BindLogic logic={sessionTabLogic} props={{ timestamp, sessionId }}>
                        <TabsPrimitive value={currentSessionTab} onValueChange={setCurrentSessionTab}>
                            <SubHeader className="p-0">
                                <TabsPrimitiveList className="flex justify-start gap-2 w-full h-full items-center">
                                    <TabsPrimitiveTrigger className="px-2 h-full" value="timeline">
                                        Timeline
                                    </TabsPrimitiveTrigger>
                                    <TabsPrimitiveTrigger className="px-2 h-full" value="recording">
                                        Recording
                                    </TabsPrimitiveTrigger>
                                </TabsPrimitiveList>
                            </SubHeader>
                            <SessionTimeline value="timeline" />
                            <SessionRecording value="recording" />
                        </TabsPrimitive>
                    </BindLogic>
                ))
                .exhaustive()}
        </TabsPrimitiveContent>
    )
}

export function NoSessionIdFound(): JSX.Element {
    return (
        <div className="flex justify-center w-full h-[300px] items-center">
            <EmptyMessage
                title="No session found"
                description="There is no $session_id associated with this exception. If it was captured from a server
                SDK, you can read our doc on how to forward session IDs"
                buttonText="Check doc"
                buttonTo="https://posthog.com/docs/data/sessions#server-sdks-and-sessions"
                size="small"
            />
        </div>
    )
}
