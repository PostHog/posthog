package env

// -------------------------------------------------------------
// Go Language Versioned Environment Schemas (Strictly Typed)
// -------------------------------------------------------------

// Base Go Environment (Common across all Go 1.11+ toolchains)
#GoBaseEnv: {
	GO_VERSION?:  #SemVer | *"1.24"
	CGO_ENABLED?: 0 | 1 | *0
	GO111MODULE?: "on" | "off" | "auto" | *"on"
	GOTOOLCHAIN?: "auto" | "local" | "path" | string | *"auto"
	[string]:     _
}

// Go 1.11 - Go 1.15 (Legacy Module Transition Era)
#Go1_15Env: #GoBaseEnv

// Go 1.16 - Go 1.20 (Modules on by default, GOPRIVATE standard)
#Go1_20Env: #GoBaseEnv

// Go 1.21 - Go 1.23 (GOTOOLCHAIN auto management, loopvar experiment)
#Go1_23Env: #GoBaseEnv

// Go 1.24+ (Modern Go: synctest testing primitive, swissmap runtime)
#Go1_24Env: #GoBaseEnv

// Parameterized Go Environment
#Go: #GoBaseEnv

// Default Go environment alias
#GoEnv: #Go
