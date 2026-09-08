package env

// -------------------------------------------------------------
// Zig Language Versioned Environment Schemas (Strictly Typed)
// -------------------------------------------------------------

// Base Zig Environment
#ZigBaseEnv: {
	ZIG_VERSION?:          #SemVer | *"0.14"
	ZIG_GLOBAL_CACHE_DIR?: string
	ZIG_LOCAL_CACHE_DIR?:  string
	[string]:              _
}

// Parameterized Zig Environment
// Usage: env.#Zig or env.#Zig & { ZIG_VERSION: "0.14.0" }
#Zig: #ZigBaseEnv & {
	ZIG_VERSION?:          #SemVer | *"0.14"
	ZIG_GLOBAL_CACHE_DIR?: string
	ZIG_LOCAL_CACHE_DIR?:  string
}

// Default Zig environment alias
#ZigEnv: #Zig
