package pkgs

import devshell "github.com/tonky/enve/schema/v1:schema"

// -------------------------------------------------------------
// Language Toolchains, Servers, Linters & Formatters
// -------------------------------------------------------------

gopls: devshell.#GoBuildSpec & {
	pname:       "gopls"
	version:     "0.18.1"
	src:         "https://github.com/golang/tools/archive/refs/tags/gopls/v0.18.1.tar.gz"
	subPackages: "gopls"
}

go: devshell.#GoBuildSpec & {
	pname:   "go"
	version: "1.24.0"
	src:     "https://go.dev/dl/go1.24.0.src.tar.gz"
}

golang: go

golangci_lint: devshell.#GoBuildSpec & {
	pname:       "golangci-lint"
	version:     "1.64.5"
	src:         "https://github.com/golangci/golangci-lint/archive/refs/tags/v1.64.5.tar.gz"
	subPackages: "cmd/golangci-lint"
}

cargo: devshell.#BuildSpec & {
	pname:   "cargo"
	version: "1.98.0"
	src:     "https://github.com/rust-lang/cargo/archive/refs/tags/1.98.0.tar.gz"
}

rustc: devshell.#BuildSpec & {
	pname:   "rustc"
	version: "1.98.0"
	src:     "https://static.rust-lang.org/dist/rustc-1.98.0-src.tar.gz"
}

rustc_1_98: rustc
rustc_1_97: devshell.#BuildSpec & {
	pname:   "rustc"
	version: "1.97.1"
	src:     "https://static.rust-lang.org/dist/rustc-1.97.1-src.tar.gz"
}

clippy: devshell.#BuildSpec & {
	pname:   "clippy"
	version: "1.98.0"
	src:     "https://github.com/rust-lang/rust-clippy/archive/refs/tags/0.1.98.tar.gz"
}

rust: cargo

rust_analyzer: devshell.#RustBuildSpec & {
	pname:   "rust-analyzer"
	version: "2026-08-03"
	src:     "https://github.com/rust-lang/rust-analyzer/archive/refs/tags/2026-08-03.tar.gz"
}

ruff: devshell.#PythonBuildSpec & {
	pname:   "ruff"
	version: "0.16.1"
	src:     "https://github.com/astral-sh/ruff/archive/refs/tags/v0.16.1.tar.gz"
	format:  "pyproject"
}

pyright: devshell.#NodeBuildSpec & {
	pname:   "pyright"
	version: "1.1.394"
	src:     "https://github.com/microsoft/pyright/archive/refs/tags/1.1.394.tar.gz"
}

prettier: devshell.#NodeBuildSpec & {
	pname:   "prettier"
	version: "3.8.3"
	src:     "https://github.com/prettier/prettier/archive/refs/tags/3.8.3.tar.gz"
}

biome: devshell.#RustBuildSpec & {
	pname:   "biome"
	version: "1.9.4"
	src:     "https://github.com/biomejs/biome/archive/refs/tags/cli/v1.9.4.tar.gz"
}

zls: devshell.#RustBuildSpec & {
	pname:   "zls"
	version: "0.14.0"
	src:     "https://github.com/zigtools/zls/archive/refs/tags/0.14.0.tar.gz"
}

bun: devshell.#RustBuildSpec & {
	pname:   "bun"
	version: "1.3.13"
	src:     "https://github.com/oven-sh/bun/archive/refs/tags/bun-v1.3.13.tar.gz"
}

deno: devshell.#RustBuildSpec & {
	pname:   "deno"
	version: "2.9.5"
	src:     "https://github.com/denoland/deno/archive/refs/tags/v2.9.5.tar.gz"
}

ruby: devshell.#RustBuildSpec & {
	pname:   "ruby"
	version: "3.4.1"
	src:     "https://github.com/ruby/ruby/archive/refs/tags/v3_4_1.tar.gz"
}

gleam: devshell.#RustBuildSpec & {
	pname:   "gleam"
	version: "1.8.1"
	src:     "https://github.com/gleam-lang/gleam/archive/refs/tags/v1.8.1.tar.gz"
}

erlang: devshell.#BuildSpec & {
	pname:   "erlang"
	version: "28.5.0.5"
	src:     "https://github.com/erlang/otp/archive/refs/tags/OTP-28.5.0.5.tar.gz"
}

erlang_27: devshell.#BuildSpec & {
	pname:   "erlang_27"
	version: "27.3.4"
	src:     "https://github.com/erlang/otp/archive/refs/tags/OTP-27.3.4.tar.gz"
}

erlang_28: devshell.#BuildSpec & {
	pname:   "erlang_28"
	version: "28.5.0.5"
	src:     "https://github.com/erlang/otp/archive/refs/tags/OTP-28.5.0.5.tar.gz"
}

elixir: devshell.#BuildSpec & {
	pname:   "elixir"
	version: "1.18.5"
	src:     "https://github.com/elixir-lang/elixir/archive/refs/tags/v1.18.5.tar.gz"
}

elixir_otp27: devshell.#BuildSpec & {
	pname:   "elixir_otp27"
	version: "1.18.5"
	src:     "https://github.com/elixir-lang/elixir/archive/refs/tags/v1.18.5.tar.gz"
}

elixir_otp28: devshell.#BuildSpec & {
	pname:   "elixir_otp28"
	version: "1.18.5"
	src:     "https://github.com/elixir-lang/elixir/archive/refs/tags/v1.18.5.tar.gz"
}

rebar3: devshell.#BuildSpec & {
	pname:   "rebar3"
	version: "3.27.0"
	src:     "https://github.com/erlang/rebar3/archive/refs/tags/3.27.0.tar.gz"
}

rebar3_otp27: devshell.#BuildSpec & {
	pname:   "rebar3_otp27"
	version: "3.27.0"
	src:     "https://github.com/erlang/rebar3/archive/refs/tags/3.27.0.tar.gz"
}

rebar3_otp28: devshell.#BuildSpec & {
	pname:   "rebar3_otp28"
	version: "3.27.0"
	src:     "https://github.com/erlang/rebar3/archive/refs/tags/3.27.0.tar.gz"
}

hex: devshell.#BuildSpec & {
	pname:   "hex"
	version: "2.5.1"
	src:     "https://github.com/hexpm/hex/archive/v2.5.1.tar.gz"
}

hex_otp27: devshell.#BuildSpec & {
	pname:   "hex_otp27"
	version: "2.5.1"
	src:     "https://github.com/hexpm/hex/archive/v2.5.1.tar.gz"
}

hex_otp28: devshell.#BuildSpec & {
	pname:   "hex_otp28"
	version: "2.5.1"
	src:     "https://github.com/hexpm/hex/archive/v2.5.1.tar.gz"
}

nodejs: devshell.#BuildSpec & {
	pname:   "nodejs"
	version: "22.14.0"
	src:     "https://nodejs.org/dist/v22.14.0/node-v22.14.0.tar.gz"
}

node: nodejs

flutter: devshell.#BuildSpec & {
	pname:   "flutter"
	version: "3.47.0"
	src:     "https://github.com/flutter/flutter/archive/refs/tags/3.47.0.tar.gz"
}
