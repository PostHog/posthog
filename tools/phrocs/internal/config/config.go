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
