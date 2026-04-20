package config

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"gopkg.in/yaml.v3"
)

// CapabilityGroupKey is the reserved key under ProcConfig.Groups that carries
// the capability dimension inferred from ProcConfig.Capability
const CapabilityGroupKey = "capability"

// Mirrors a single entry under mprocs.yaml's "procs" key
type ProcConfig struct {
	Shell        string            `yaml:"shell"`
	Capability   string            `yaml:"capability"`
	Cmd          []string          `yaml:"cmd"`
	Cwd          string            `yaml:"cwd"`
	Autostart    *bool             `yaml:"autostart"`
	Autorestart  bool              `yaml:"autorestart"`
	Stop         string            `yaml:"stop"` // "SIGINT", "SIGTERM", "SIGKILL", or "hard-kill"
	AskSkip      bool              `yaml:"ask_skip"`
	Env          map[string]string `yaml:"env"`
	ReadyPattern string            `yaml:"ready_pattern"`
	Groups       map[string]string `yaml:"groups"` // user-defined grouping dimensions, using map here so new dimensions need no code changes
}

// Reports whether the process should start automatically
// Defaults to true when the field is absent from the YAML
func (p ProcConfig) ShouldAutostart() bool {
	return p.Autostart == nil || *p.Autostart
}

// Top-level mprocs.yaml document
type Config struct {
	Shell            string                `yaml:"shell"`
	Procs            map[string]ProcConfig `yaml:"procs"`
	GroupOrder       map[string][]string   `yaml:"group_order"` // display order per dimension
	HideKeymapWindow bool                  `yaml:"hide_keymap_window"`
	MouseScrollSpeed int                   `yaml:"mouse_scroll_speed"`
	ProcListWidth    int                   `yaml:"proc_list_width"`
	Scrollback       int                   `yaml:"scrollback"`
}

// ResolveConfigPath returns the config file path to use. If explicit is
// non-empty it is returned as-is. Otherwise, the function checks for an
// mprocs.yaml in the current directory and returns its path, or an error
// if no config can be found.
func ResolveConfigPath(explicit string) (string, error) {
	if explicit != "" {
		return explicit, nil
	}
	info, err := os.Stat("mprocs.yaml")
	if err == nil && info.Mode().IsRegular() {
		return "mprocs.yaml", nil
	}
	if err == nil {
		return "", fmt.Errorf("mprocs.yaml exists but is not a regular file")
	}
	if os.IsNotExist(err) {
		return "", fmt.Errorf("no config: pass --config or place an mprocs.yaml in the current directory")
	}
	return "", fmt.Errorf("stat mprocs.yaml: %w", err)
}

// Reads and parses an mprocs-compatible YAML config file
func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}
	if cfg.Scrollback == 0 {
		cfg.Scrollback = 10_000
	}
	if cfg.MouseScrollSpeed == 0 {
		cfg.MouseScrollSpeed = 3
	}
	inferGroupFromCapability(&cfg)
	return &cfg, nil
}

// inferGroupFromCapability copies each proc's "capability:" field into
// "groups:" map, so the TUI's grouping dimension cycle ("g" key) picks
// it up alongside user-declared dimensions.
// An explicit Groups[CapabilityGroupKey] in YAML takes precedence.
func inferGroupFromCapability(cfg *Config) {
	for name, pc := range cfg.Procs {
		if pc.Capability == "" {
			// Procs without a capability fall under "Ungrouped"
			continue
		}
		if _, ok := pc.Groups[CapabilityGroupKey]; ok {
			// Any explicit entry is respected, setting to "" leads to "Ungrouped"
			continue
		}
		if pc.Groups == nil {
			pc.Groups = make(map[string]string)
		}
		pc.Groups[CapabilityGroupKey] = pc.Capability
		cfg.Procs[name] = pc
	}
}

// Intent is a minimal representation of an intent from intent-map.yaml.
type Intent struct {
	Name        string
	Description string
}

// IntentMapConfig holds just enough of intent-map.yaml to display intents in the TUI.
type IntentMapConfig struct {
	Intents []Intent
}

// LoadIntentMap finds and parses devenv/intent-map.yaml by walking up from
// the working directory. Returns the parsed intents sorted by name.
func LoadIntentMap() (*IntentMapConfig, error) {
	path, err := findIntentMapPath()
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var raw struct {
		Intents map[string]struct {
			Description string `yaml:"description"`
		} `yaml:"intents"`
	}
	if err := yaml.Unmarshal(data, &raw); err != nil {
		return nil, err
	}
	if raw.Intents == nil {
		return nil, fmt.Errorf("intent-map missing 'intents' mapping")
	}
	intents := make([]Intent, 0, len(raw.Intents))
	for name, fields := range raw.Intents {
		intents = append(intents, Intent{Name: name, Description: fields.Description})
	}
	sort.Slice(intents, func(i, j int) bool { return intents[i].Name < intents[j].Name })
	return &IntentMapConfig{Intents: intents}, nil
}

// findIntentMapPath walks up from the working directory looking for
// devenv/intent-map.yaml. Falls back to the cwd-relative path.
func findIntentMapPath() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("get working directory: %w", err)
	}
	for {
		candidate := filepath.Join(dir, "devenv", "intent-map.yaml")
		if _, err := os.Stat(candidate); err == nil {
			return candidate, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return filepath.Join("devenv", "intent-map.yaml"), nil
		}
		dir = parent
	}
}

// PosthogConfig represents the _posthog section embedded in generated mprocs configs.
type PosthogConfig struct {
	Intents      []string `yaml:"intents"`
	ExcludeUnits []string `yaml:"exclude_units"`
}

// LoadPosthogConfig reads a generated mprocs.yaml and extracts the _posthog section.
// Returns nil (no error) if the section is absent.
func LoadPosthogConfig(configPath string) (*PosthogConfig, error) {
	data, err := os.ReadFile(configPath)
	if err != nil {
		return nil, err
	}
	var wrapper struct {
		Posthog *PosthogConfig `yaml:"_posthog"`
	}
	if err := yaml.Unmarshal(data, &wrapper); err != nil {
		return nil, err
	}
	return wrapper.Posthog, nil
}

// OrderedNames returns process names in a stable, predictable order.
// "info" is always first (if present), then remaining names sorted alphabetically.
func (c *Config) OrderedNames() []string {
	names := make([]string, 0, len(c.Procs))
	for name := range c.Procs {
		if name != "info" {
			names = append(names, name)
		}
	}
	sort.Strings(names)
	if _, ok := c.Procs["info"]; ok {
		names = append([]string{"info"}, names...)
	}
	return names
}
