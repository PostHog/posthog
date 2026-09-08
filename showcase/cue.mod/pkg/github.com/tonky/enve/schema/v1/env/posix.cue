package env

// -------------------------------------------------------------
// POSIX & Shell Standard Environment Schemas
// -------------------------------------------------------------

#PosixEnv: {
	PAGER?:   "less" | "more" | "cat" | string | *"less"
	EDITOR?:  "nano" | "vim" | "nvim" | "helix" | "emacs" | "code" | string | *"nano"
	[string]: _
}

// Parameterized POSIX environment alias
#Posix: #PosixEnv
