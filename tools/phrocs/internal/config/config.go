package config

import (
	"fmt"
	"os"
	"sort"

	"gopkg.in/yaml.v3"
)

// Mirrors a single entry under mprocs.yaml's "procs" key
type ProcConfig struct {
	Shell        string            `yaml:"shell"`
	Capability   string            `yaml:"capability"`
	Cmd          []string          `yaml:"cmd"`
	Autostart    *bool             `yaml:"autostart"`
	Autorestart  bool              `yaml:"autorestart"`
	Stop         string            `yaml:"stop"` // "SIGINT", "SIGTERM", "SIGKILL", or "hard-kill"
	AskSkip      bool              `yaml:"ask_skip"`
	Env          map[string]string `yaml:"env"`
	ReadyPattern string            `yaml:"ready_pattern"`
}

// Reports whether the process should start automatically
// Defaults to true when the field is absent from the YAML
func (p ProcConfig) ShouldAutostart() bool {
	return p.Autostart == nil || *p.Autostart
}

// Top-level mprocs.yaml document
type Config struct {
	Procs            map[string]ProcConfig `yaml:"procs"`
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
	return &cfg, nil
}

// Intent is a minimal representation of an intent from intent-map.yaml.
type Intent struct {
	Name        string
	Description string
}

// IntentMapConfig holds just enough of intent-map.yaml to display intents in the TUI.
// Intents are kept in YAML definition order.
type IntentMapConfig struct {
	Intents []Intent
}

// LoadIntentMap reads devenv/intent-map.yaml and returns the parsed intents
// in the order they appear in the file.
func LoadIntentMap(path string) (*IntentMapConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var doc yaml.Node
	if err := yaml.Unmarshal(data, &doc); err != nil {
		return nil, err
	}
	if doc.Kind != yaml.DocumentNode || len(doc.Content) == 0 {
		return nil, fmt.Errorf("invalid intent-map document")
	}
	root := doc.Content[0]
	if root.Kind != yaml.MappingNode {
		return nil, fmt.Errorf("intent-map root must be a mapping")
	}

	// Find the "intents" key in the top-level mapping
	var intentsNode *yaml.Node
	for i := 0; i+1 < len(root.Content); i += 2 {
		if root.Content[i].Value == "intents" {
			intentsNode = root.Content[i+1]
			break
		}
	}
	if intentsNode == nil || intentsNode.Kind != yaml.MappingNode {
		return nil, fmt.Errorf("intent-map missing 'intents' mapping")
	}

	// Walk key/value pairs in definition order
	var intents []Intent
	for i := 0; i+1 < len(intentsNode.Content); i += 2 {
		name := intentsNode.Content[i].Value
		valNode := intentsNode.Content[i+1]

		var fields struct {
			Description string `yaml:"description"`
		}
		if err := valNode.Decode(&fields); err != nil {
			return nil, fmt.Errorf("decode intent %q: %w", name, err)
		}
		intents = append(intents, Intent{Name: name, Description: fields.Description})
	}

	return &IntentMapConfig{Intents: intents}, nil
}

// PosthogConfig represents the _posthog section embedded in generated mprocs configs.
type PosthogConfig struct {
	Intents []string `yaml:"intents"`
}

// LoadPosthogConfig reads a generated mprocs.yaml and extracts the _posthog section.
// Returns nil (no error) if the section is absent.
func LoadPosthogConfig(configPath string) (*PosthogConfig, error) {
	data, err := os.ReadFile(configPath)
	if err != nil {
		return nil, err
	}
	var raw map[string]interface{}
	if err := yaml.Unmarshal(data, &raw); err != nil {
		return nil, err
	}
	phSection, ok := raw["_posthog"]
	if !ok {
		return nil, nil
	}
	// Re-marshal and unmarshal the _posthog section into PosthogConfig
	phBytes, err := yaml.Marshal(phSection)
	if err != nil {
		return nil, err
	}
	var cfg PosthogConfig
	if err := yaml.Unmarshal(phBytes, &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
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
