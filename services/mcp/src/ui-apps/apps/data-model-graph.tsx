import '../styles/tailwind.css'
import '@xyflow/react/dist/style.css'

import { createRoot } from 'react-dom/client'

import { type DataModelGraphData, DataModelGraphView } from 'products/data_modeling/mcp/apps'

import { AppWrapper } from '../components/AppWrapper'

function DataModelGraphApp(): JSX.Element {
    return (
        <AppWrapper<DataModelGraphData> appName="PostHog Data Model Lineage">
            {({ data }) => <DataModelGraphView data={data!} />}
        </AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<DataModelGraphApp />)
}
