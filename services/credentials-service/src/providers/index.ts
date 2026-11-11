// The provider registry. Add a kind with one spec file and one line here, then run
// `hogli build:projections --only credentials-catalogue` to regenerate the Python catalogue.
//
// This module and everything it imports must stay free of npm packages: the catalogue bundle
// builds in a CI job that has no node_modules. Validation lives in `./validate`.

import { github } from './github'
import { googleAds } from './google-ads'
import { googleCloudStorage } from './google-cloud-storage'
import { googleSheets } from './google-sheets'
import { hubspot } from './hubspot'
import { linear } from './linear'
import { salesforce } from './salesforce'
import type { ProviderSpec } from './schema'
import { slack } from './slack'

export const PROVIDER_SPECS: readonly ProviderSpec[] = [
    github,
    googleAds,
    googleCloudStorage,
    googleSheets,
    hubspot,
    linear,
    salesforce,
    slack,
]

const BY_KIND: ReadonlyMap<string, ProviderSpec> = new Map(PROVIDER_SPECS.map((spec) => [spec.kind, spec]))

/** The spec of a kind, or undefined for a kind that the service does not serve yet. */
/** The config keys of a kind that only create and exchange may set. Empty for an unknown kind. */
export function identityConfigKeys(kind: string): readonly string[] {
    return BY_KIND.get(kind)?.identityConfigKeys ?? []
}

export function providerSpec(kind: string): ProviderSpec | undefined {
    return BY_KIND.get(kind)
}
