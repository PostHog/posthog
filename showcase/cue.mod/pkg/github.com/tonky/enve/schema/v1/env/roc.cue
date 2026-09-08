package env

// -------------------------------------------------------------
// Roc Language Versioned Environment Schemas (Strictly Typed)
// -------------------------------------------------------------

// Base Roc Environment
#RocBaseEnv: {
	ROC_VERSION?:   #SemVer | *"0.1"
	ROC_CACHE_DIR?: string
	[string]:       _
}

// Parameterized Roc Environment
// Usage: env.#Roc or env.#Roc & { ROC_VERSION: "0.1.0" }
#Roc: #RocBaseEnv & {
	ROC_VERSION?:   #SemVer | *"0.1"
	ROC_CACHE_DIR?: string
}

// Default Roc environment alias
#RocEnv: #Roc
