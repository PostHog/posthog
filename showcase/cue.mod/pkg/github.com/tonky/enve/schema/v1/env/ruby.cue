package env

// -------------------------------------------------------------
// Ruby Language Environment Schema (Strictly Typed)
// -------------------------------------------------------------

#RubyBaseEnv: {
	RUBY_VERSION?:     #SemVer | *"3.3"
	RAILS_ENV?:        "development" | "production" | "test" | *"development"
	RUBY_YJIT_ENABLE?: 0 | 1 | *1
	[string]:          _
}

// Parameterized Ruby Environment
// Usage: env.#Ruby or env.#Ruby & { RUBY_VERSION: "3.3.1", RAILS_ENV: "production" }
#Ruby: #RubyBaseEnv & {
	RUBY_VERSION?:     #SemVer | *"3.3"
	RAILS_ENV?:        "development" | "production" | "test" | *"development"
	RUBY_YJIT_ENABLE?: 0 | 1 | *1
}

// Ruby 3.3 and 3.4 aliases
#Ruby3_3Env: #RubyBaseEnv & {
	RUBY_VERSION: "3.3"
}

#Ruby3_4Env: #RubyBaseEnv & {
	RUBY_VERSION: "3.4"
}

// Default Ruby environment alias
#RubyEnv: #Ruby
