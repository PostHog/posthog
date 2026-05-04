package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func chdir(t *testing.T, dir string) {
	t.Helper()
	orig, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(orig); err != nil {
			t.Fatal(err)
		}
	})
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
}

func writeYAML(t *testing.T, content string) string {
	t.Helper()
	f, err := os.CreateTemp(t.TempDir(), "*.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteString(content); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	return f.Name()
}

func TestLoad_defaults(t *testing.T) {
	path := writeYAML(t, "procs:\n  backend:\n    shell: echo hi\n")
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Scrollback != 10_000 {
		t.Errorf("Scrollback: got %d, want 10000", cfg.Scrollback)
	}
	if cfg.MouseScrollSpeed != 3 {
		t.Errorf("MouseScrollSpeed: got %d, want 3", cfg.MouseScrollSpeed)
	}
}

func TestLoad_explicit(t *testing.T) {
	path := writeYAML(t, "scrollback: 500\nmouse_scroll_speed: 7\nprocs:\n  backend:\n    shell: echo hi\n")
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Scrollback != 500 {
		t.Errorf("Scrollback: got %d, want 500", cfg.Scrollback)
	}
	if cfg.MouseScrollSpeed != 7 {
		t.Errorf("MouseScrollSpeed: got %d, want 7", cfg.MouseScrollSpeed)
	}
}

func TestLoad_missingFile(t *testing.T) {
	_, err := Load(filepath.Join(t.TempDir(), "nonexistent.yaml"))
	if err == nil {
		t.Error("expected error for missing file, got nil")
	}
}

func TestLoad_invalidYAML(t *testing.T) {
	path := writeYAML(t, ":\t: bad yaml\n")
	_, err := Load(path)
	if err == nil {
		t.Error("expected error for invalid YAML, got nil")
	}
}

func TestOrderedNames(t *testing.T) {
	tests := []struct {
		name  string
		procs []string
		want  []string
	}{
		{
			name:  "info first, rest alphabetical",
			procs: []string{"backend", "info", "frontend", "celery"},
			want:  []string{"info", "backend", "celery", "frontend"},
		},
		{
			name:  "no info, alphabetical",
			procs: []string{"backend", "frontend", "celery"},
			want:  []string{"backend", "celery", "frontend"},
		},
		{
			name:  "only info",
			procs: []string{"info"},
			want:  []string{"info"},
		},
		{
			name:  "empty",
			procs: []string{},
			want:  []string{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := &Config{Procs: make(map[string]ProcConfig, len(tt.procs))}
			for _, n := range tt.procs {
				cfg.Procs[n] = ProcConfig{}
			}
			got := cfg.OrderedNames()
			if len(got) != len(tt.want) {
				t.Fatalf("got %v, want %v", got, tt.want)
			}
			for i, name := range got {
				if name != tt.want[i] {
					t.Errorf("index %d: got %q, want %q", i, name, tt.want[i])
				}
			}
		})
	}
}

func TestShouldAutostart(t *testing.T) {
	boolPtr := func(b bool) *bool { return &b }
	tests := []struct {
		name      string
		autostart *bool
		want      bool
	}{
		{"nil defaults to true", nil, true},
		{"explicit true", boolPtr(true), true},
		{"explicit false", boolPtr(false), false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			p := ProcConfig{Autostart: tt.autostart}
			if got := p.ShouldAutostart(); got != tt.want {
				t.Errorf("got %v, want %v", got, tt.want)
			}
		})
	}
}

func TestLoad_cmd(t *testing.T) {
	path := writeYAML(t, `
procs:
  svc:
    cmd: ["node", "index.js", "--port=3000"]
`)
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	p := cfg.Procs["svc"]
	if len(p.Cmd) != 3 || p.Cmd[0] != "node" || p.Cmd[1] != "index.js" || p.Cmd[2] != "--port=3000" {
		t.Errorf("Cmd: got %v, want [node index.js --port=3000]", p.Cmd)
	}
}

func TestLoad_stopSignal(t *testing.T) {
	tests := []struct {
		name string
		yaml string
		want string
	}{
		{"SIGINT", "stop: SIGINT", "SIGINT"},
		{"SIGTERM", "stop: SIGTERM", "SIGTERM"},
		{"SIGKILL", "stop: SIGKILL", "SIGKILL"},
		{"hard-kill", "stop: hard-kill", "hard-kill"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			path := writeYAML(t, "procs:\n  svc:\n    shell: echo hi\n    "+tt.yaml+"\n")
			cfg, err := Load(path)
			if err != nil {
				t.Fatal(err)
			}
			if got := cfg.Procs["svc"].Stop; got != tt.want {
				t.Errorf("Stop: got %q, want %q", got, tt.want)
			}
		})
	}
}

func TestLoad_hideKeymapWindow(t *testing.T) {
	path := writeYAML(t, "hide_keymap_window: true\nprocs:\n  svc:\n    shell: echo hi\n")
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.HideKeymapWindow {
		t.Error("HideKeymapWindow: got false, want true")
	}
}

func TestLoad_procListWidth(t *testing.T) {
	path := writeYAML(t, "proc_list_width: 30\nprocs:\n  svc:\n    shell: echo hi\n")
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.ProcListWidth != 30 {
		t.Errorf("ProcListWidth: got %d, want 30", cfg.ProcListWidth)
	}
}

func TestLoad_globalShell(t *testing.T) {
	path := writeYAML(t, "shell: /bin/zsh\nprocs:\n  svc:\n    shell: echo hi\n")
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Shell != "/bin/zsh" {
		t.Errorf("Shell: got %q, want %q", cfg.Shell, "/bin/zsh")
	}
}

func TestLoad_infersCapabilityGroup(t *testing.T) {
	tests := []struct {
		name       string
		yaml       string
		proc       string
		wantCap    string // expected Groups["capability"] value (may be "")
		wantAbsent bool   // if true, expect the key to be missing entirely
	}{
		{
			name:    "copies capability into groups",
			yaml:    "procs:\n  svc:\n    shell: echo hi\n    capability: event_ingestion\n",
			proc:    "svc",
			wantCap: "event_ingestion",
		},
		{
			name:       "missing capability field leaves groups untouched",
			yaml:       "procs:\n  svc:\n    shell: echo hi\n",
			proc:       "svc",
			wantAbsent: true,
		},
		{
			name:    "explicit groups.capability in YAML takes precedence",
			yaml:    "procs:\n  svc:\n    shell: echo hi\n    capability: event_ingestion\n    groups:\n      capability: pinned\n",
			proc:    "svc",
			wantCap: "pinned",
		},
		{
			// Explicit empty override opts the proc out of capability grouping
			// (i.e. later put into Ungrouped)
			name:    "empty explicit override opts out of inference",
			yaml:    "procs:\n  svc:\n    shell: echo hi\n    capability: event_ingestion\n    groups:\n      capability: \"\"\n",
			proc:    "svc",
			wantCap: "",
		},
		{
			name:    "preserves sibling groups while adding capability",
			yaml:    "procs:\n  svc:\n    shell: echo hi\n    capability: flag_evaluation\n    groups:\n      layer: Product services\n",
			proc:    "svc",
			wantCap: "flag_evaluation",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			path := writeYAML(t, tt.yaml)
			cfg, err := Load(path)
			if err != nil {
				t.Fatal(err)
			}
			got, ok := cfg.Procs[tt.proc].Groups["capability"]
			if tt.wantAbsent {
				if ok {
					t.Errorf("unexpected Groups[\"capability\"]=%q, want absent", got)
				}
				return
			}
			if !ok {
				t.Fatalf("Groups[\"capability\"] missing, want %q", tt.wantCap)
			}
			if got != tt.wantCap {
				t.Errorf("Groups[\"capability\"]: got %q, want %q", got, tt.wantCap)
			}
		})
	}
}

func TestLoad_inferCapabilityPreservesLayerAndTech(t *testing.T) {
	path := writeYAML(t, `
procs:
  svc:
    shell: echo hi
    capability: event_ingestion
    groups:
      layer: Processing
      tech: Rust
`)
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	g := cfg.Procs["svc"].Groups
	if g["layer"] != "Processing" || g["tech"] != "Rust" || g["capability"] != "event_ingestion" {
		t.Errorf("expected layer=Processing tech=Rust capability=event_ingestion, got %+v", g)
	}
}

func TestLoad_cwd(t *testing.T) {
	path := writeYAML(t, "procs:\n  svc:\n    shell: echo hi\n    cwd: /tmp/mydir\n")
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Procs["svc"].Cwd != "/tmp/mydir" {
		t.Errorf("Cwd: got %q, want %q", cfg.Procs["svc"].Cwd, "/tmp/mydir")
	}
}

func TestLoadPosthogConfig(t *testing.T) {
	path := writeYAML(t, `
procs:
  svc:
    shell: echo hi
_posthog:
  intents:
    - web
    - analytics
  exclude_units:
    - celery
`)
	cfg, err := LoadPosthogConfig(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil PosthogConfig")
	}
	if len(cfg.Intents) != 2 || cfg.Intents[0] != "web" || cfg.Intents[1] != "analytics" {
		t.Errorf("Intents: got %v, want [web analytics]", cfg.Intents)
	}
	if len(cfg.ExcludeUnits) != 1 || cfg.ExcludeUnits[0] != "celery" {
		t.Errorf("ExcludeUnits: got %v, want [celery]", cfg.ExcludeUnits)
	}
}

func TestLoadPosthogConfig_absent(t *testing.T) {
	path := writeYAML(t, "procs:\n  svc:\n    shell: echo hi\n")
	cfg, err := LoadPosthogConfig(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg != nil {
		t.Errorf("expected nil when _posthog absent, got %+v", cfg)
	}
}

func TestResolveConfigPath(t *testing.T) {
	t.Run("explicit path is returned as-is", func(t *testing.T) {
		got, err := ResolveConfigPath("/some/explicit/path.yaml")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if got != "/some/explicit/path.yaml" {
			t.Errorf("got %q, want %q", got, "/some/explicit/path.yaml")
		}
	})

	t.Run("defaults to mprocs.yaml in cwd", func(t *testing.T) {
		dir := t.TempDir()
		if err := os.WriteFile(filepath.Join(dir, "mprocs.yaml"), []byte("procs: {}\n"), 0o644); err != nil {
			t.Fatal(err)
		}
		chdir(t, dir)

		got, err := ResolveConfigPath("")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if got != "mprocs.yaml" {
			t.Errorf("got %q, want %q", got, "mprocs.yaml")
		}
	})

	t.Run("error when no mprocs.yaml exists", func(t *testing.T) {
		dir := t.TempDir()
		chdir(t, dir)

		_, err := ResolveConfigPath("")
		if err == nil {
			t.Fatal("expected error, got nil")
		}
		if !strings.Contains(err.Error(), "no config") {
			t.Errorf("error %q should mention 'no config'", err)
		}
	})

	t.Run("skips mprocs.yaml if it is a directory", func(t *testing.T) {
		dir := t.TempDir()
		if err := os.Mkdir(filepath.Join(dir, "mprocs.yaml"), 0o755); err != nil {
			t.Fatal(err)
		}
		chdir(t, dir)

		_, err := ResolveConfigPath("")
		if err == nil {
			t.Fatal("expected error when mprocs.yaml is a directory, got nil")
		}
		if !strings.Contains(err.Error(), "not a regular file") {
			t.Errorf("error %q should mention 'not a regular file'", err)
		}
	})
}
