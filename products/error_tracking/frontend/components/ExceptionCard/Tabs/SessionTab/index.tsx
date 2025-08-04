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
import { NotFound } from 'lib/components/NotFound'
import { Link } from '@posthog/lemon-ui'

export interface SessionTabProps extends TabsPrimitiveContentProps {
    timestamp?: string
}

export function SessionTab({ timestamp, ...props }: SessionTabProps): JSX.Element {
    const { sessionId } = useValues(errorPropertiesLogic)
    return (
        <TabsPrimitiveContent {...props}>
            {match([sessionId])
                .with([P.nullish], () => (
                    <NotFound
                        object="session"
                        caption={
                            <span>
                                No session is associated with this exception. <br /> If it was captured from a server
                                SDK, you can read{' '}
                                <Link to="https://posthog.com/docs/data/sessions#server-sdks-and-sessions">
                                    our guide
                                </Link>{' '}
                                on how to forward session ids.
                            </span>
                        }
                    />
                ))
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
