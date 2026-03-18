package docker

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/charmbracelet/x/ansi"
)

func installFakeDocker(t *testing.T, script string) {
	t.Helper()
	dir := t.TempDir()
	binPath := filepath.Join(dir, "docker")
	if err := os.WriteFile(binPath, []byte(script), 0o755); err != nil {
		t.Fatalf("write fake docker: %v", err)
	}
	oldPath := os.Getenv("PATH")
	t.Setenv("PATH", dir+string(os.PathListSeparator)+oldPath)
}

func TestIsDockerComposeShell(t *testing.T) {
	tests := []struct {
		shell string
		want  bool
	}{
		{shell: "docker compose up", want: true},
		{shell: "docker-compose up", want: true},
		{shell: "pnpm dev", want: false},
	}

	for _, tc := range tests {
		t.Run(tc.shell, func(t *testing.T) {
			if got := IsDockerComposeShell(tc.shell); got != tc.want {
				t.Fatalf("IsDockerComposeShell(%q) = %v, want %v", tc.shell, got, tc.want)
			}
		})
	}
}

func TestParseComposeArgs(t *testing.T) {
	tests := []struct {
		name     string
		shell    string
		files    []string
		profiles []string
	}{
		{
			name:  "single file",
			shell: "docker compose -f docker-compose.dev.yml up",
			files: []string{"docker-compose.dev.yml"},
		},
		{
			name:     "multiple files and profile",
			shell:    "docker compose -f docker-compose.dev.yml -f docker-compose.profiles.yml --profile tracing up",
			files:    []string{"docker-compose.dev.yml", "docker-compose.profiles.yml"},
			profiles: []string{"tracing"},
		},
		{
			name:  "no flags",
			shell: "docker compose up",
		},
		{
			name:  "dash f at end",
			shell: "docker compose -f",
		},
		{
			name:     "equals syntax",
			shell:    "docker compose --file=a.yml --profile=dev up",
			files:    []string{"a.yml"},
			profiles: []string{"dev"},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := ParseComposeArgs(tc.shell)
			if strings.Join(got.Files, ",") != strings.Join(tc.files, ",") {
				t.Fatalf("Files = %v, want %v", got.Files, tc.files)
			}
			if strings.Join(got.Profiles, ",") != strings.Join(tc.profiles, ",") {
				t.Fatalf("Profiles = %v, want %v", got.Profiles, tc.profiles)
			}
		})
	}
}

func TestStripComposeLogsTail(t *testing.T) {
	tests := []struct {
		name  string
		shell string
		want  string
	}{
		{
			name:  "strips trailing logs",
			shell: "docker compose -f a.yml up -d && echo ready && docker compose -f a.yml logs --tail=100 -f",
			want:  "docker compose -f a.yml up -d && echo ready",
		},
		{
			name:  "no logs tail",
			shell: "docker compose -f a.yml up -d && echo ready",
			want:  "docker compose -f a.yml up -d && echo ready",
		},
		{
			name:  "single segment",
			shell: "docker compose up",
			want:  "docker compose up",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := StripComposeLogsTail(tc.shell); got != tc.want {
				t.Fatalf("StripComposeLogsTail() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestComposeBaseArgs(t *testing.T) {
	if got := composeBaseArgs(ComposeArgs{}); strings.Join(got, " ") != "compose" {
		t.Fatalf("composeBaseArgs(empty) = %v", got)
	}
	args := ComposeArgs{Files: []string{"docker-compose.dev.yml"}}
	if got := composeBaseArgs(args); strings.Join(got, " ") != "compose -f docker-compose.dev.yml" {
		t.Fatalf("composeBaseArgs(with file) = %v", got)
	}
	args2 := ComposeArgs{
		Files:    []string{"docker-compose.dev.yml", "docker-compose.profiles.yml"},
		Profiles: []string{"tracing"},
	}
	want := "compose -f docker-compose.dev.yml -f docker-compose.profiles.yml --profile tracing"
	if got := composeBaseArgs(args2); strings.Join(got, " ") != want {
		t.Fatalf("composeBaseArgs(multi) = %v, want %v", got, want)
	}
}

func TestFetchContainerListParsesAndSorts(t *testing.T) {
	installFakeDocker(t, `#!/bin/sh
set -eu
cat <<'EOF'
{"Service":"zeta","Status":"Up 10s","State":"running"}
this-is-not-json
{"Service":"alpha","Status":"Exited (1)","State":"exited"}
EOF
`)

	args := ComposeArgs{Files: []string{"docker-compose.dev.yml"}}
	msg := FetchContainerList(args)()
	listMsg, ok := msg.(ContainerListMsg)
	if !ok {
		t.Fatalf("message type = %T, want ContainerListMsg", msg)
	}
	if len(listMsg.Containers) != 2 {
		t.Fatalf("container count = %d, want 2", len(listMsg.Containers))
	}
	if listMsg.Containers[0].Service != "alpha" || listMsg.Containers[1].Service != "zeta" {
		t.Fatalf("containers not sorted by service: %+v", listMsg.Containers)
	}
}

func TestFetchContainerListCommandFailure(t *testing.T) {
	installFakeDocker(t, "#!/bin/sh\nexit 1\n")

	args := ComposeArgs{Files: []string{"docker-compose.dev.yml"}}
	msg := FetchContainerList(args)()
	listMsg, ok := msg.(ContainerListMsg)
	if !ok {
		t.Fatalf("message type = %T, want ContainerListMsg", msg)
	}
	if len(listMsg.Containers) != 0 {
		t.Fatalf("container count = %d, want 0", len(listMsg.Containers))
	}
}

func TestRenderContainerStatusTableEmpty(t *testing.T) {
	if got := RenderContainerStatusTable(nil, 80); got != "  Waiting for containers..." {
		t.Fatalf("unexpected empty-state table: %q", got)
	}
}

func TestRenderContainerStatusTableContainsColumnsAndRows(t *testing.T) {
	table := RenderContainerStatusTable([]DockerContainer{
		{Service: "very-long-service-name", State: "running", Status: "Up 10m"},
		{Service: "db", State: "exited", Status: "Exited (1)"},
	}, 36)
	plain := ansi.Strip(table)

	for _, part := range []string{"SERVICE", "STATE", "STATUS", "db"} {
		if !strings.Contains(plain, part) {
			t.Fatalf("table missing %q:\n%s", part, plain)
		}
	}

	if !strings.Contains(plain, "very-long-s") {
		t.Fatalf("expected truncated service name in table:\n%s", plain)
	}
}

func TestStopNilStreamDoesNotPanic(t *testing.T) {
	var stream *ContainerLogStream
	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("Stop panicked: %v", r)
		}
	}()
	stream.Stop()
}

func TestMaxContainerLogLinesConstant(t *testing.T) {
	if MaxContainerLogLines <= 0 {
		t.Fatalf("MaxContainerLogLines must be positive, got %d", MaxContainerLogLines)
	}
	if MaxContainerLogLines < 100 {
		t.Fatalf("MaxContainerLogLines unexpectedly low: %d", MaxContainerLogLines)
	}
}

func TestFetchContainerListUsesComposeArgsShape(t *testing.T) {
	argsFile := filepath.Join(t.TempDir(), "args.txt")
	installFakeDocker(t, fmt.Sprintf(`#!/bin/sh
set -eu
printf "%%s\n" "$@" > %q
echo '{"Service":"one","Status":"Up","State":"running"}'
`, argsFile))

	composeArgs := ComposeArgs{Files: []string{"docker-compose.dev.yml"}}
	_ = FetchContainerList(composeArgs)()
	gotBytes, err := os.ReadFile(argsFile)
	if err != nil {
		t.Fatalf("read args file: %v", err)
	}
	got := strings.Split(strings.TrimSpace(string(gotBytes)), "\n")
	want := []string{"compose", "-f", "docker-compose.dev.yml", "ps", "--format", "json"}
	if strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("docker args = %v, want %v", got, want)
	}
}
