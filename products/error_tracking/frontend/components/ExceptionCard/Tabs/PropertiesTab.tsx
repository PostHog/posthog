import { useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { TabsContent, TabsContentProps } from 'lib/ui/Tabs'

import { ContextDisplay } from '../../ContextDisplay'
import { exceptionCardLogic } from '../exceptionCardLogic'

export interface PropertiesTabProps extends TabsContentProps {}

export function PropertiesTab({ ...props }: PropertiesTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    const { exceptionAttributes, additionalProperties } = useValues(errorPropertiesLogic)
    return (
        <TabsContent {...props}>
            <ContextDisplay
                className="w-full p-2"
                attributes={exceptionAttributes ?? undefined}
                additionalProperties={additionalProperties}
                loading={loading}
            />
        </TabsContent>
    )
}
