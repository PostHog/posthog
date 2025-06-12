import { useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { JSONViewer } from 'lib/components/JSONViewer'
import { TabsContent, TabsContentProps } from 'lib/ui/Tabs'

export interface RawTabProps extends TabsContentProps {}

export function RawTab(props: RawTabProps): JSX.Element {
    const { properties } = useValues(errorPropertiesLogic)
    return (
        <TabsContent {...props}>
            <JSONViewer src={properties} name="event" collapsed={1} collapseStringsAfterLength={80} sortKeys />
        </TabsContent>
    )
}
