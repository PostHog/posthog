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
import { BindLogic, useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { sessionTabLogic } from './sessionTabLogic'
import { match, P } from 'ts-pattern'

export interface SessionTabProps extends TabsPrimitiveContentProps {
    timestamp?: string
}

export function SessionTab({ timestamp, ...props }: SessionTabProps): JSX.Element {
    const { sessionId } = useValues(errorPropertiesLogic)
    return (
        <TabsPrimitiveContent {...props}>
            {match([sessionId])
                .with([P.nullish], () => <div>No session ID</div>)
                .with([P.string], ([sessionId]) => (
                    <BindLogic logic={sessionTabLogic} props={{ timestamp, sessionId }}>
                        <TabsPrimitive defaultValue="timeline">
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
