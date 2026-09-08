package env

// -------------------------------------------------------------
// WebAssembly Environment Schemas
// -------------------------------------------------------------

#WasmBaseEnv: {
	CC?:                                          string | *"clang"
	CC_wasm32_unknown_unknown?:                   string | *"/nix/store/603yaax3l2jmc0hfv6g3hgjr1qk5jfxk-clang-21.1.8/bin/clang"
	CFLAGS_wasm32_unknown_unknown?:               string | *"-resource-dir=/nix/store/w021fbcg4z6vxihnp6gb6vijyifl051f-clang-wrapper-21.1.8/resource-root"
	CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER: string | *"gcc"
	[string]:                                     _
}

#WasmEnv: #WasmBaseEnv
