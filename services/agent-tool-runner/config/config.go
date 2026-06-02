// Package config defines the runner's YAML configuration shape and a
// loader+validator. The shape mirrors the example in
// docs/agent-platform/plans/self-hosted-tool-runners.md verbatim.
package config

import (
	"errors"
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

// Config is the top-level runner configuration. Every project entry in
// `Projects` becomes an independent register-heartbeat-poll loop at runtime
// — they are unrelated from PostHog's perspective (different tool_runner
// rows, possibly different endpoints).
type Config struct {
	// Projects this runner serves. Each entry is fully independent.
	Projects []ProjectConfig `yaml:"projects"`

	// Tool sources shared by all project loops. Source secrets / endpoints
	// are per-process (per the spec). A `ProjectConfig.Expose` entry
	// references a tool by its `<source_name>.<tool_name>` path here.
	ToolSources []ToolSourceConfig `yaml:"tool_sources"`
}

// ProjectConfig is one (endpoint, token, slug) registration.
type ProjectConfig struct {
	// PostHog project ID this binding registers under.
	ProjectID int `yaml:"project_id"`

	// PostHog ingress base URL. May differ per project — supports hybrid
	// US / EU / self-hosted setups from one runner process.
	Endpoint string `yaml:"endpoint"`

	// Path of a file containing the bearer token. The chart wires this
	// from a K8s Secret into the pod. We deliberately do not accept the
	// token inline in YAML so a misconfigured `kubectl describe` does not
	// leak it.
	TokenSecretRef string `yaml:"token_secret_ref"`

	// Project-stable identifier for this runner — must match the slug the
	// admin created in the PostHog UI when minting the token.
	Slug string `yaml:"slug"`

	// Subset of `ToolSources` to expose to this project, in
	// `<source_name>.<tool_name>` form. Different projects may expose
	// different subsets; e.g. prod gets read-only Grafana, staging gets
	// the full set.
	Expose []string `yaml:"expose"`
}

// ToolSourceConfig discriminates on `Source`. Exactly one of the embedded
// variants is populated per entry.
type ToolSourceConfig struct {
	// "mcp" | "command". Other sources may be added by the reference
	// runner in the future without touching the platform contract.
	Source string `yaml:"source"`

	// Common to all sources — the prefix used in `ProjectConfig.Expose`.
	Name string `yaml:"name"`

	// Optional free-text shown to agents + surfaced in the PostHog UI
	// catalog preview. MCP sources usually leave this empty since the
	// upstream MCP server publishes its own per-tool descriptions.
	Description string `yaml:"description,omitempty"`

	// `source: mcp` fields.
	Endpoint    string   `yaml:"endpoint,omitempty"`
	SecretsEnvs []string `yaml:"secrets_envs,omitempty"`

	// `source: command` fields.
	ArgsSchema map[string]any `yaml:"args_schema,omitempty"`
	Command    string         `yaml:"command,omitempty"`
}

// Load reads and validates the runner configuration at the given path.
func Load(path string) (*Config, error) {
	bytes, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read config %s: %w", path, err)
	}
	var cfg Config
	if err := yaml.Unmarshal(bytes, &cfg); err != nil {
		return nil, fmt.Errorf("parse config %s: %w", path, err)
	}
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid config %s: %w", path, err)
	}
	return &cfg, nil
}

// Validate is split out so tests can exercise the validation rules without
// loading from disk.
func (c *Config) Validate() error {
	if len(c.Projects) == 0 {
		return errors.New("at least one entry under `projects:` is required")
	}

	sourcesByName := make(map[string]*ToolSourceConfig, len(c.ToolSources))
	for i := range c.ToolSources {
		s := &c.ToolSources[i]
		if err := s.validate(); err != nil {
			return fmt.Errorf("tool_sources[%d]: %w", i, err)
		}
		if _, exists := sourcesByName[s.Name]; exists {
			return fmt.Errorf("tool_sources[%d]: duplicate name %q", i, s.Name)
		}
		sourcesByName[s.Name] = s
	}

	for i, p := range c.Projects {
		if err := p.validate(); err != nil {
			return fmt.Errorf("projects[%d]: %w", i, err)
		}
		for j, exposed := range p.Expose {
			source, _, ok := splitQualifiedName(exposed)
			if !ok {
				return fmt.Errorf(
					"projects[%d].expose[%d]: %q must be in `<source>.<tool>` form",
					i, j, exposed,
				)
			}
			// Two ways an expose entry can reference a tool_source:
			//   1. Prefix match: `grafana.query_loki` resolves to source
			//      named `grafana` (which contributes many tools under
			//      its prefix). Used by MCP sources.
			//   2. Exact match: `kubernetes.restart_deployment` resolves
			//      to a source named `kubernetes.restart_deployment`
			//      (which is itself one tool). Used by command sources,
			//      whose name embeds the dot.
			if _, ok := sourcesByName[exposed]; ok {
				continue
			}
			if _, ok := sourcesByName[source]; ok {
				continue
			}
			return fmt.Errorf(
				"projects[%d].expose[%d]: no tool source defined for %q",
				i, j, exposed,
			)
		}
	}
	return nil
}

func (p *ProjectConfig) validate() error {
	if p.ProjectID <= 0 {
		return errors.New("project_id is required and must be positive")
	}
	if p.Endpoint == "" {
		return errors.New("endpoint is required")
	}
	if p.TokenSecretRef == "" {
		return errors.New("token_secret_ref is required")
	}
	if p.Slug == "" {
		return errors.New("slug is required")
	}
	if len(p.Expose) == 0 {
		return errors.New("expose must list at least one tool")
	}
	return nil
}

func (s *ToolSourceConfig) validate() error {
	if s.Name == "" {
		return errors.New("name is required")
	}
	switch s.Source {
	case "mcp":
		if s.Endpoint == "" {
			return errors.New("source: mcp requires endpoint")
		}
	case "command":
		if s.Command == "" {
			return errors.New("source: command requires command")
		}
	case "":
		return errors.New("source is required")
	default:
		return fmt.Errorf("unknown source %q (expected: mcp, command)", s.Source)
	}
	return nil
}

// splitQualifiedName splits `<source>.<tool>` into its parts. The first
// dot is the separator — tool names may themselves contain dots. Returns
// (source, tool, true) only when both parts are non-empty; otherwise
// returns ("", "", false) so callers can't accidentally rely on a
// half-parsed value.
func splitQualifiedName(qualified string) (source, tool string, ok bool) {
	for i := range len(qualified) {
		if qualified[i] == '.' {
			if i == 0 || i == len(qualified)-1 {
				return "", "", false
			}
			return qualified[:i], qualified[i+1:], true
		}
	}
	return "", "", false
}
