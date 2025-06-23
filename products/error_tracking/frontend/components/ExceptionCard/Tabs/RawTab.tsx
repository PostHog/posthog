import { useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { JSONViewer } from 'lib/components/JSONViewer'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'

export interface RawTabProps extends TabsPrimitiveContentProps {}

export function RawTab(props: RawTabProps): JSX.Element {
    const { properties } = useValues(errorPropertiesLogic)
    return (
        <TabsPrimitiveContent className="p-2" {...props}>
            <JSONViewer src={properties} name="event" collapsed={1} collapseStringsAfterLength={80} sortKeys />
        </TabsPrimitiveContent>
    )
}
