package env

// -------------------------------------------------------------
// Gleam Language Environment Schema (Strictly Typed)
// -------------------------------------------------------------

#GleamBaseEnv: {
	GLEAM_VERSION?: #SemVer | *"1.8"
	GLEAM_LOG?:     "error" | "warn" | "info" | "debug" | "trace" | string | *"info"
	GLEAM_TARGET?:  "erlang" | "javascript" | *"erlang"
	[string]:       _
}

// Gleam 1.8+ (Modern compiler with full Erlang & JS target support)
#Gleam1_8Env: #GleamBaseEnv & {
	GLEAM_TARGET: "erlang"
}

// Parameterized Gleam Environment
// Usage: env.#Gleam or env.#Gleam & { GLEAM_VERSION: "1.8.1", GLEAM_LOG: "debug" }
#Gleam: #GleamBaseEnv & {
	GLEAM_VERSION?: #SemVer | *"1.8"
	GLEAM_LOG?:     "error" | "warn" | "info" | "debug" | "trace" | string | *"info"
	GLEAM_TARGET?:  "erlang" | "javascript" | *"erlang"
}

// Default Gleam environment alias
#GleamEnv: #Gleam
