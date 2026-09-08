package env

// -------------------------------------------------------------
// Rust Language Versioned Environment Schemas (Strictly Typed)
// -------------------------------------------------------------

// Base Rust Environment
#RustBaseEnv: {
	RUST_VERSION?:                        #SemVer | *"1.98.0"
	RUST_BACKTRACE?:                      0 | 1 | "full" | *1
	RUST_LOG?:                            "error" | "warn" | "info" | "debug" | "trace" | string | *"info"
	CARGO_TERM_COLOR?:                    "always" | "auto" | "never" | *"always"
	CARGO_REGISTRIES_CRATES_IO_PROTOCOL?: "sparse" | "git" | *"sparse"
	[string]:                             _
}

// Rust 1.70 - 1.79 (Sparse index protocol default)
#Rust1_70Env: #RustBaseEnv & {
	CARGO_REGISTRIES_CRATES_IO_PROTOCOL: "sparse"
}

// Rust 1.80 - 1.84 (Custom lints, cargo check color enhancements)
#Rust1_80Env: #Rust1_70Env & {
	CARGO_TERM_COLOR: "always"
}

// Rust 1.85+ (Rust 2024 Edition baseline)
#Rust1_85Env: #Rust1_80Env

// Rust 1.98+ (Latest generation)
#Rust1_98Env: #Rust1_85Env

// Parameterized Rust Environment
// Usage: env.#Rust or env.#Rust & { RUST_VERSION: "1.98.0", RUST_LOG: "debug" }
#Rust: #RustBaseEnv & {
	RUST_VERSION?:                        #SemVer | *"1.98.0"
	RUST_BACKTRACE?:                      0 | 1 | "full" | *1
	CARGO_TERM_COLOR?:                    "always" | "auto" | "never" | *"always"
	CARGO_REGISTRIES_CRATES_IO_PROTOCOL?: "sparse" | "git" | *"sparse"
}

// Default Rust environment alias
#RustEnv: #Rust
