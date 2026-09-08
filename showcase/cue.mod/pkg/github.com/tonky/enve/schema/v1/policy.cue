package devshell

// -------------------------------------------------------------
// enve Shield: Supply Chain Security & Policy Schemas
// -------------------------------------------------------------

#VulnerabilitySeverity: "none" | "low" | "medium" | "high" | "critical"

#LicensePolicy: {
	// Explicitly allowed SPDX license identifiers (e.g. ["MIT", "Apache-2.0", "BSD-3-Clause"])
	allowedLicenses?: [...string]

	// Explicitly prohibited SPDX license identifiers (e.g. ["GPL-3.0-only", "AGPL-3.0-only"])
	bannedLicenses?: [...string]

	// Reject any package whose license cannot be deterministically verified
	allowUnknownLicenses: bool | *false
}

#ToolchainPolicy: {
	// Minimum allowed toolchain / runtime versions
	// e.g. python: "3.12", go: "1.23", rust: "1.80", node: "20.0"
	minVersions?: [string]: string

	// Explicitly disallowed package versions or packages
	bannedPackages?: [...string]

	// Require cryptographic source hashes (sha256) on all build specifications
	requireHermeticHashes: bool | *true
}

#SecurityPolicy: {
	name:        string & !=""
	description?: string

	// Maximum allowable vulnerability threshold before build/CI failure
	vulnerabilityTolerance: #VulnerabilitySeverity | *"none"

	// License compliance enforcement rules
	licensePolicy?: #LicensePolicy

	// Compiler & toolchain baseline requirements
	toolchainPolicy?: #ToolchainPolicy

	// Enforce that enve.lock exists and is strictly valid
	requireLockfile: bool | *true
}
