// Build-time stub for the AWS credential providers this service must never use.
//
// The SDK's runtimeConfig imports the whole default provider chain statically, so
// esbuild bundles SSO, shared-INI, `credential_process` and IMDS even though we always
// pass an explicit `credentials` (see credentials.ts) and none of them can ever be
// reached at runtime. The esbuild config aliases those modules here instead.
//
// Two things this buys beyond a smaller bundle: the service physically cannot fall back
// to a developer's SSO cache or an EC2 instance role if the explicit provider is ever
// dropped by accident, and we stop having to keep those packages' transitive tree
// compatible with the monorepo's pinned @smithy/* versions.

function refuse(name: string): () => never {
    return () => {
        throw new Error(
            `The ${name} AWS credential provider is deliberately not available in integration-service. ` +
                'Credentials come from the IRSA web identity token (see src/aws/credentials.ts).'
        )
    }
}

export const fromSSO = refuse('SSO')
export const fromIni = refuse('shared INI profile')
export const fromProcess = refuse('credential_process')
export const fromInstanceMetadata = refuse('EC2 instance metadata')
export const fromContainerMetadata = refuse('ECS container metadata')
export const fromEnv = refuse('environment')
export const nodeProvider = refuse('default Node chain')
export const defaultProvider = refuse('default Node chain')
