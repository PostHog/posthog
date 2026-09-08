package env

// -------------------------------------------------------------
// Python Language Versioned Environment Schemas (Strictly Typed)
// -------------------------------------------------------------

// Base Python Environment
#PythonBaseEnv: {
	PYTHON_VERSION?:          #SemVer | *"3.13"
	PYTHONUNBUFFERED?:        0 | 1 | *1
	PYTHONDONTWRITEBYTECODE?: 0 | 1 | *1
	[string]:                 _
}

// Python 3.10 - 3.11
#Python3_11Env: #PythonBaseEnv

// Python 3.12+ (Safe sys.path isolation, isolated build backend defaults)
#Python3_12Env: #PythonBaseEnv

// Python 3.13+ (Free-threaded GIL support, JIT experiments)
#Python3_13Env: #PythonBaseEnv

// Parameterized Python Environment
// Usage: env.#Python or env.#Python & { PYTHON_VERSION: "3.12", PYTHONUNBUFFERED: 1 }
#Python: #PythonBaseEnv & {
	PYTHON_VERSION?:          #SemVer | *"3.13"
	PYTHONUNBUFFERED?:        0 | 1 | *1
	PYTHONDONTWRITEBYTECODE?: 0 | 1 | *1
}

// Default Python environment alias
#PythonEnv: #Python
