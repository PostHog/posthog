import { useValues } from 'kea'
import { router } from 'kea-router'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { EndpointsTab, endpointsLogic } from './endpointsLogic'
import { QuillEndpoints } from './QuillEndpoints'
import { QuillEndpointsUsage } from './QuillEndpointsUsage'

export function QuillEndpointsTabs(): JSX.Element {
    const { activeTab } = useValues(endpointsLogic)

    return (
        <Tabs
            value={activeTab}
            onValueChange={(tab: EndpointsTab) =>
                router.actions.push(tab === 'usage' ? urls.endpointsUsage() : urls.endpoints())
            }
            data-quill
            data-attr="endpoints-tabs"
        >
            <TabsList variant="line" aria-label="Endpoints sections">
                <TabsTrigger value="endpoints" data-attr="endpoints-tab">
                    Endpoints
                </TabsTrigger>
                <TabsTrigger value="usage" data-attr="endpoints-usage-tab">
                    Usage
                </TabsTrigger>
            </TabsList>
            <TabsContent value="endpoints" className="pt-4 pb-8">
                <QuillEndpoints />
            </TabsContent>
            <TabsContent value="usage" className="pt-4 pb-8">
                <QuillEndpointsUsage />
            </TabsContent>
        </Tabs>
    )
}
