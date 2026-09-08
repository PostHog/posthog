package env

// -------------------------------------------------------------
// Node / TypeScript Versioned Environment Schemas (Strictly Typed)
// -------------------------------------------------------------

// Base Node Environment
#NodeBaseEnv: {
	NODE_VERSION?:        #SemVer | *"22"
	NODE_ENV?:            "development" | "production" | "test" | *"development"
	NPM_CONFIG_LOGLEVEL?: "silent" | "error" | "warn" | "info" | "verbose" | *"warn"
	[string]:             _
}

// Node.js 18 LTS
#Node18Env: #NodeBaseEnv

// Node.js 20 LTS (Next.js & modern web toolchain)
#Node20Env: #NodeBaseEnv

// Node.js 22 LTS (On-disk code caching, native WebSocket defaults)
#Node22Env: #NodeBaseEnv

// Parameterized Node.js Environment
// Usage: env.#Node or env.#Node & { NODE_VERSION: "20", PORT: 3000 }
#Node: #NodeBaseEnv & {
	NODE_VERSION?:        #SemVer | *"22"
	NODE_ENV?:            "development" | "production" | "test" | *"development"
	NPM_CONFIG_LOGLEVEL?: "silent" | "error" | "warn" | "info" | "verbose" | *"warn"
}

// Default Node environment alias
#NodeEnv: #Node
