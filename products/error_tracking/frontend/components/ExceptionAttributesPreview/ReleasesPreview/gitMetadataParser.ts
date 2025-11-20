export type GitProvider = 'github' | 'gitlab' | 'bitbucket' | 'unknown'
export const supportedProviders = ['github', 'gitlab']

export type ParsedRemoteUrl = {
    provider: GitProvider
    owner: string
    repository: string
    providerUrl: string | undefined
}

export class GitMetadataParser {
    static getCommitLink(remote_url?: string, commit_id?: string): string | undefined {
        if (!commit_id || !remote_url) {
            return undefined
        }
        const parsedRemoteUrl = this.parseRemoteUrl(remote_url)
        if (!parsedRemoteUrl) {
            return undefined
        }
        return this.buildCommitLink(parsedRemoteUrl, commit_id)
    }

    static getBranchLink(remote_url?: string, branch?: string): string | undefined {
        if (!remote_url || !branch) {
            return undefined
        }
        const parsedRemoteUrl = this.parseRemoteUrl(remote_url)
        if (!parsedRemoteUrl) {
            return undefined
        }
        return this.buildBranchLink(parsedRemoteUrl, branch)
    }

    static getRepoLink(remote_url?: string): string | undefined {
        if (!remote_url) {
            return undefined
        }
        const parsedRemoteUrl = this.parseRemoteUrl(remote_url)
        if (!parsedRemoteUrl) {
            return undefined
        }
        return this.buildRemoteLink(parsedRemoteUrl)
    }

    static parseRemoteUrl(remoteUrl: string): ParsedRemoteUrl | undefined {
        return this.parseSshRemoteUrl(remoteUrl) || this.parseHttpsRemoteUrl(remoteUrl)
    }

    private static buildRemoteLink(parsedUrl: ParsedRemoteUrl): string | undefined {
        switch (parsedUrl.provider) {
            case 'github':
            case 'gitlab':
            case 'bitbucket':
                return `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}`
            default:
                return undefined
        }
    }

    private static buildBranchLink(parsedUrl: ParsedRemoteUrl, branch: string): string | undefined {
        switch (parsedUrl.provider) {
            case 'github':
            case 'bitbucket':
                return `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}/tree/${branch}`
            case 'gitlab':
                return `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}/-/tree/${branch}`
            default:
                return undefined
        }
    }

    private static buildCommitLink(parsedUrl: ParsedRemoteUrl, commitSha: string): string | undefined {
        switch (parsedUrl.provider) {
            case 'github':
            case 'bitbucket':
                return `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}/commit/${commitSha}`
            case 'gitlab':
                return `${parsedUrl.providerUrl}/${parsedUrl.owner}/${parsedUrl.repository}/-/commit/${commitSha}`
            default:
                return undefined
        }
    }

    private static parseSshRemoteUrl(remoteUrl: string): ParsedRemoteUrl | undefined {
        // git@github.com:user/repo.git

        const atIdx = remoteUrl.indexOf('@')
        const colonIdx = remoteUrl.indexOf(':')
        if (atIdx === -1 || colonIdx === -1) {
            return undefined
        }
        const providerDomain = remoteUrl.slice(atIdx + 1, colonIdx)
        const [provider, providerUrl] = this.parseDomain(providerDomain)
        const afterColon = remoteUrl.slice(colonIdx + 1)
        const slashIdx = afterColon.indexOf('/')

        if (slashIdx === -1) {
            return undefined
        }

        const owner = afterColon.slice(0, slashIdx)
        let repository = afterColon.slice(slashIdx + 1)
        if (repository.endsWith('.git')) {
            repository = repository.slice(0, -4)
        }

        return { provider, owner, repository, providerUrl }
    }

    private static parseHttpsRemoteUrl(remoteUrl: string): ParsedRemoteUrl | undefined {
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

        const domain = withoutProtocol.slice(0, firstSlashIdx)
        const pathParts = withoutProtocol.slice(firstSlashIdx + 1).split('/')

        if (pathParts.length < 2) {
            return undefined
        }

        const owner = pathParts[0]
        let repository = pathParts[1]
        if (repository.endsWith('.git')) {
            repository = repository.slice(0, -4)
        }

        const [provider, providerUrl] = this.parseDomain(domain)

        return { provider, owner, repository, providerUrl }
    }

    private static parseDomain(domain: string): [GitProvider, string | undefined] {
        switch (domain) {
            case 'github.com':
                return ['github', 'https://github.com']
            case 'gitlab.com':
                return ['gitlab', 'https://gitlab.com']
            case 'bitbucket.org':
                return ['bitbucket', 'https://bitbucket.org']
            default:
                return ['unknown', `https://${domain}/`]
        }
    }
}
