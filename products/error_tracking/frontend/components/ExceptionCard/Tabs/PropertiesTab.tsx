import { useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'

import { ContextDisplay } from '../../ContextDisplay'
import { exceptionCardLogic } from '../exceptionCardLogic'

export interface PropertiesTabProps extends TabsPrimitiveContentProps {}

export function PropertiesTab({ ...props }: PropertiesTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    const { exceptionAttributes, additionalProperties } = useValues(errorPropertiesLogic)
    return (
        <TabsPrimitiveContent {...props}>
            <ContextDisplay
                className="w-full p-2"
                attributes={exceptionAttributes ?? undefined}
                additionalProperties={additionalProperties}
                loading={loading}
            />
        </TabsPrimitiveContent>
    )
}
