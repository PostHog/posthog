import '../../styles/base.css'

import { createRoot } from 'react-dom/client'

import { AppWrapper } from '../../components/AppWrapper'
import { Component } from '../../components/Component'

function QueryResultsApp(): JSX.Element {
    return <AppWrapper appName="PostHog Query Results">{({ data }) => <Component data={data} />}</AppWrapper>
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<QueryResultsApp />)
}
