package config

import (
	"os"
	"sort"

	"gopkg.in/yaml.v3"
)

// Mirrors a single entry under mprocs.yaml's "procs" key
type ProcConfig struct {
	Shell        string            `yaml:"shell"`
	Capability   string            `yaml:"capability"`
	Autostart    *bool             `yaml:"autostart"`
	Autorestart  bool              `yaml:"autorestart"`
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
	MouseScrollSpeed int                   `yaml:"mouse_scroll_speed"`
	Scrollback       int                   `yaml:"scrollback"`
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
