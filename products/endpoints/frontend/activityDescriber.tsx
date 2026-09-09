import {
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

interface EndpointActivityContext {
    version?: number
}

function getVersionFromContext(context: EndpointActivityContext | null | undefined): number | undefined {
    return context?.version
}

function EndpointLink({ name, version }: { name: string; version?: number }): JSX.Element {
    return <Link to={urls.endpoint(name, version)}>{name}</Link>
}

function VersionLink({ name, version }: { name: string; version: number }): JSX.Element {
    return <Link to={urls.endpoint(name, version)}>v{version}</Link>
}

export function endpointActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'Endpoint' && logItem.scope !== 'EndpointVersion') {
        console.error('endpoint describer received a non-endpoint activity')
        return { description: null }
    }

    const endpointName = logItem.detail.name ?? logItem.item_id ?? 'unknown'
    const context = logItem.detail.context as EndpointActivityContext | null | undefined
    const version = getVersionFromContext(context)

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> created endpoint <EndpointLink name={endpointName} /> (
                    <VersionLink name={endpointName} version={1} />
                    ).
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted endpoint <strong>{endpointName}</strong>.
                </>
            ),
        }
    }

    if (logItem.activity === 'version_created' && version !== undefined) {
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> created version{' '}
                    <VersionLink name={endpointName} version={version} /> of endpoint{' '}
                    <EndpointLink name={endpointName} />.
                </>
            ),
        }
    }

    if (logItem.activity === 'version_updated' && version !== undefined) {
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> updated{' '}
                    <VersionLink name={endpointName} version={version} /> of endpoint{' '}
                    <EndpointLink name={endpointName} />.
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> updated endpoint <EndpointLink name={endpointName} />.
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, <EndpointLink name={endpointName} />)
}
