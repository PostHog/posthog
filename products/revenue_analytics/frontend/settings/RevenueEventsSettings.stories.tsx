import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

const meta: Meta = {
    title: 'Scenes-App/Data Management',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.REVENUE_ANALYTICS],
    },
}
export default meta

export function RevenueEventsSettings(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.revenueSettings())
    }, [])
    return <App />
}
