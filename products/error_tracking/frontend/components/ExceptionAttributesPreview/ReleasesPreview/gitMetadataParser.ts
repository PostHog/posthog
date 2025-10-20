import { ErrorTrackingRelease } from 'lib/components/Errors/types'

export type GitProvider = 'github' | 'unknown'

export class GitMetadataParser {
    static getViewCommitLink(release: ErrorTrackingRelease): string | undefined {
        const hasRemoteUrl = release.metadata?.git?.remote_url !== undefined
        const hasCommitId = release.metadata?.git?.commit_id !== undefined

        const remoteUrl = release.metadata?.git?.remote_url ?? ''
        const commitId = release.metadata?.git?.commit_id ?? ''

        return hasRemoteUrl && hasCommitId ? this.resolveRemoteUrlWithCommitToLink(remoteUrl, commitId) : undefined
    }

    static parseRemoteUrl(remoteUrl: string): { provider: GitProvider; owner: string; repository: string } | null {
        const parsed = this.parseSshRemoteUrl(remoteUrl) || this.parseHttpsRemoteUrl(remoteUrl)

        if (!parsed) {
            return null
        }

        if (parsed.providerUrl.includes('github')) {
            return {
                provider: 'github',
                owner: parsed.user,
                repository: parsed.path,
            }
        }

        return {
            provider: 'unknown',
            owner: parsed.user,
            repository: parsed.path,
        }
    }

    static resolveRemoteUrlWithCommitToLink(remoteUrl: string, commitSha: string): string | undefined {
        let parsed = GitMetadataParser.parseSshRemoteUrl(remoteUrl)

        if (!parsed) {
            parsed = GitMetadataParser.parseHttpsRemoteUrl(remoteUrl)
        }

        if (!parsed?.providerUrl.includes('github')) {
            return undefined
        }

        return `${parsed.providerUrl}/${parsed.user}/${parsed.path}/commit/${commitSha}`
    }

    static parseSshRemoteUrl(remoteUrl: string): { providerUrl: string; user: string; path: string } | undefined {
        // git@github.com:user/repo.git

        const atIdx = remoteUrl.indexOf('@')
        const colonIdx = remoteUrl.indexOf(':')
        if (atIdx === -1 || colonIdx === -1) {
            return undefined
        }
        const providerDomain = remoteUrl.slice(atIdx + 1, colonIdx)
        const provider = `https://${providerDomain}`
        const afterColon = remoteUrl.slice(colonIdx + 1)
        const slashIdx = afterColon.indexOf('/')
        if (slashIdx === -1) {
            return undefined
        }
        const user = afterColon.slice(0, slashIdx)
        let path = afterColon.slice(slashIdx + 1)
        if (path.endsWith('.git')) {
            path = path.slice(0, -4)
        }
        return { providerUrl: provider, user, path }
    }

    static parseHttpsRemoteUrl(remoteUrl: string): { providerUrl: string; user: string; path: string } | undefined {
        // https://github.com/user/repo.git

        const httpsPrefix = 'https://'
        if (!remoteUrl.startsWith(httpsPrefix)) {
            return undefined
        }

        const withoutProtocol = remoteUrl.slice(httpsPrefix.length)
        const firstSlashIdx = withoutProtocol.indexOf('/')
        if (firstSlashIdx === -1) {
            return undefined
        }

        const provider = `https://${withoutProtocol.slice(0, firstSlashIdx)}`
        const pathParts = withoutProtocol.slice(firstSlashIdx + 1).split('/')

        if (pathParts.length < 2) {
            return undefined
        }

        const user = pathParts[0]
        let path = pathParts[1]
        if (path.endsWith('.git')) {
            path = path.slice(0, -4)
        }

        return { providerUrl: provider, user, path }
    }
}
