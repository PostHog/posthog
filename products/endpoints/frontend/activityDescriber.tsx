import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
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
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> created endpoint{' '}
                    <EndpointLink name={endpointName} />.
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted endpoint{' '}
                    <strong>{endpointName}</strong>.
                </>
            ),
        }
    }

    if (logItem.activity === 'version_created' && version !== undefined) {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> created version{' '}
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
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> updated{' '}
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
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> updated endpoint{' '}
                    <EndpointLink name={endpointName} />.
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, <EndpointLink name={endpointName} />)
}
