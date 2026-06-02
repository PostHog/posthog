package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const validYAML = `
projects:
  - project_id: 123
    endpoint: https://us.posthog.com
    token_secret_ref: /run/secrets/token
    slug: grafana-prod
    expose: [grafana.query_loki]

tool_sources:
  - source: mcp
    name: grafana
    endpoint: http://grafana-mcp:3000
`

func TestLoad_Valid(t *testing.T) {
	cfg := writeAndLoad(t, validYAML)
	if len(cfg.Projects) != 1 {
		t.Fatalf("expected 1 project, got %d", len(cfg.Projects))
	}
	if cfg.Projects[0].ProjectID != 123 {
		t.Errorf("expected project_id=123, got %d", cfg.Projects[0].ProjectID)
	}
	if len(cfg.ToolSources) != 1 || cfg.ToolSources[0].Name != "grafana" {
		t.Errorf("expected one `grafana` tool source")
	}
}

func TestLoad_FileNotFound(t *testing.T) {
	_, err := Load("/nonexistent/config.yaml")
	if err == nil {
		t.Fatal("expected error for missing file")
	}
}

func TestLoad_MalformedYAML(t *testing.T) {
	_, err := loadFromString(t, "projects: [: not yaml")
	if err == nil {
		t.Fatal("expected parse error")
	}
	if !strings.Contains(err.Error(), "parse config") {
		t.Errorf("expected parse-error wrapping, got: %v", err)
	}
}

func TestValidate(t *testing.T) {
	cases := []struct {
		name    string
		cfg     Config
		wantErr string
	}{
		{
			name:    "no projects",
			cfg:     Config{},
			wantErr: "at least one entry under `projects:` is required",
		},
		{
			name: "project missing endpoint",
			cfg: Config{
				Projects: []ProjectConfig{{
					ProjectID: 1, TokenSecretRef: "x", Slug: "s", Expose: []string{"a.b"},
				}},
				ToolSources: []ToolSourceConfig{{Source: "mcp", Name: "a", Endpoint: "x"}},
			},
			wantErr: "endpoint is required",
		},
		{
			name: "project missing token ref",
			cfg: Config{
				Projects: []ProjectConfig{{
					ProjectID: 1, Endpoint: "https://x", Slug: "s", Expose: []string{"a.b"},
				}},
				ToolSources: []ToolSourceConfig{{Source: "mcp", Name: "a", Endpoint: "x"}},
			},
			wantErr: "token_secret_ref is required",
		},
		{
			name: "project missing slug",
			cfg: Config{
				Projects: []ProjectConfig{{
					ProjectID: 1, Endpoint: "https://x", TokenSecretRef: "t", Expose: []string{"a.b"},
				}},
				ToolSources: []ToolSourceConfig{{Source: "mcp", Name: "a", Endpoint: "x"}},
			},
			wantErr: "slug is required",
		},
		{
			name: "project expose is empty",
			cfg: Config{
				Projects: []ProjectConfig{{
					ProjectID: 1, Endpoint: "https://x", TokenSecretRef: "t", Slug: "s",
				}},
			},
			wantErr: "expose must list at least one tool",
		},
		{
			name: "exposed name not qualified",
			cfg: Config{
				Projects: []ProjectConfig{{
					ProjectID: 1, Endpoint: "https://x", TokenSecretRef: "t", Slug: "s",
					Expose: []string{"unqualified"},
				}},
				ToolSources: []ToolSourceConfig{{Source: "mcp", Name: "unqualified", Endpoint: "x"}},
			},
			wantErr: "`<source>.<tool>` form",
		},
		{
			name: "exposed source not declared",
			cfg: Config{
				Projects: []ProjectConfig{{
					ProjectID: 1, Endpoint: "https://x", TokenSecretRef: "t", Slug: "s",
					Expose: []string{"unknown.tool"},
				}},
			},
			wantErr: `no tool source defined for "unknown.tool"`,
		},
		{
			name: "mcp source missing endpoint",
			cfg: Config{
				Projects: []ProjectConfig{{
					ProjectID: 1, Endpoint: "https://x", TokenSecretRef: "t", Slug: "s",
					Expose: []string{"a.b"},
				}},
				ToolSources: []ToolSourceConfig{{Source: "mcp", Name: "a"}},
			},
			wantErr: "source: mcp requires endpoint",
		},
		{
			name: "command source missing command",
			cfg: Config{
				Projects: []ProjectConfig{{
					ProjectID: 1, Endpoint: "https://x", TokenSecretRef: "t", Slug: "s",
					Expose: []string{"a.b"},
				}},
				ToolSources: []ToolSourceConfig{{Source: "command", Name: "a"}},
			},
			wantErr: "source: command requires command",
		},
		{
			name: "unknown source kind",
			cfg: Config{
				Projects: []ProjectConfig{{
					ProjectID: 1, Endpoint: "https://x", TokenSecretRef: "t", Slug: "s",
					Expose: []string{"a.b"},
				}},
				ToolSources: []ToolSourceConfig{{Source: "wat", Name: "a"}},
			},
			wantErr: `unknown source "wat"`,
		},
		{
			name: "duplicate tool source names",
			cfg: Config{
				Projects: []ProjectConfig{{
					ProjectID: 1, Endpoint: "https://x", TokenSecretRef: "t", Slug: "s",
					Expose: []string{"a.b"},
				}},
				ToolSources: []ToolSourceConfig{
					{Source: "mcp", Name: "a", Endpoint: "x"},
					{Source: "mcp", Name: "a", Endpoint: "y"},
				},
			},
			wantErr: "duplicate name",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.cfg.Validate()
			if err == nil {
				t.Fatalf("expected error %q, got nil", tc.wantErr)
			}
			if !strings.Contains(err.Error(), tc.wantErr) {
				t.Errorf("expected %q, got: %v", tc.wantErr, err)
			}
		})
	}
}

// writeAndLoad and loadFromString help cut boilerplate. They write the
// given YAML to a temp file and call Load.
func writeAndLoad(t *testing.T, yaml string) *Config {
	t.Helper()
	cfg, err := loadFromString(t, yaml)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	return cfg
}

func loadFromString(t *testing.T, yaml string) (*Config, error) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(yaml), 0o600); err != nil {
		t.Fatalf("write tmp config: %v", err)
	}
	return Load(path)
}

func TestSplitQualifiedName(t *testing.T) {
	cases := []struct {
		in         string
		wantSource string
		wantTool   string
		wantOK     bool
	}{
		{"a.b", "a", "b", true},
		{"grafana.query_loki", "grafana", "query_loki", true},
		// the first dot is the separator — tool names may themselves contain dots
		{"a.b.c", "a", "b.c", true},
		{"no_dot", "", "", false},
		{".leadingdot", "", "", false},
		{"trailingdot.", "", "", false},
		{"", "", "", false},
	}
	for _, tc := range cases {
		t.Run(tc.in, func(t *testing.T) {
			gotSource, gotTool, ok := splitQualifiedName(tc.in)
			if ok != tc.wantOK || gotSource != tc.wantSource || gotTool != tc.wantTool {
				t.Errorf("splitQualifiedName(%q) = (%q, %q, %v); want (%q, %q, %v)",
					tc.in, gotSource, gotTool, ok, tc.wantSource, tc.wantTool, tc.wantOK)
			}
		})
	}
}
