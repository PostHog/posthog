package env

// -------------------------------------------------------------
// Elixir Language Versioned Environment Schemas (Strictly Typed)
// -------------------------------------------------------------

// Base Elixir Environment
#ElixirBaseEnv: {
	ELIXIR_VERSION?: #SemVer | *"1.18"
	MIX_ENV?:        "dev" | "test" | "prod" | *"dev"
	HEX_OFFLINE?:    0 | 1 | *1
	ERL_AFLAGS?:     string
	[string]:        _
}

// Parameterized Elixir Environment
// Usage: env.#Elixir or env.#Elixir & { MIX_ENV: "test", HEX_OFFLINE: 1 }
#Elixir: #ElixirBaseEnv & {
	ELIXIR_VERSION?: #SemVer | *"1.18"
	MIX_ENV?:        "dev" | "test" | "prod" | *"dev"
	HEX_OFFLINE?:    0 | 1 | *1
}

// Default Elixir environment alias
#ElixirEnv: #Elixir
