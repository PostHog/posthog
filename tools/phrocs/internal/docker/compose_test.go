package docker

import (
	"testing"
)

func TestParseContainers_JSONArray(t *testing.T) {
	data := `[{"Service":"db","Name":"posthog-db-1","State":"running","Health":"healthy"},{"Service":"redis","Name":"posthog-redis-1","State":"running","Health":""}]`
	containers := parseContainers([]byte(data))
	if len(containers) != 2 {
		t.Fatalf("expected 2 containers, got %d", len(containers))
	}
	if containers[0].Service != "db" {
		t.Errorf("expected service db, got %s", containers[0].Service)
	}
	if containers[0].State != "running" {
		t.Errorf("expected state running, got %s", containers[0].State)
	}
	if containers[0].Health != "healthy" {
		t.Errorf("expected health healthy, got %s", containers[0].Health)
	}
	if containers[1].Service != "redis" {
		t.Errorf("expected service redis, got %s", containers[1].Service)
	}
}

func TestParseContainers_NDJSON(t *testing.T) {
	data := `{"Service":"db","Name":"posthog-db-1","State":"running","Health":"healthy"}
{"Service":"kafka","Name":"posthog-kafka-1","State":"running","Health":""}`
	containers := parseContainers([]byte(data))
	if len(containers) != 2 {
		t.Fatalf("expected 2 containers, got %d", len(containers))
	}
	if containers[0].Service != "db" {
		t.Errorf("expected service db, got %s", containers[0].Service)
	}
	if containers[1].Service != "kafka" {
		t.Errorf("expected service kafka, got %s", containers[1].Service)
	}
}

func TestParseContainers_Empty(t *testing.T) {
	containers := parseContainers([]byte(""))
	if len(containers) != 0 {
		t.Fatalf("expected 0 containers, got %d", len(containers))
	}

	containers = parseContainers([]byte("  \n  "))
	if len(containers) != 0 {
		t.Fatalf("expected 0 containers, got %d", len(containers))
	}
}

func TestIsComposeCommand(t *testing.T) {
	tests := []struct {
		shell string
		want  bool
	}{
		{"docker compose -f docker-compose.dev.yml up", true},
		{"docker-compose up -d", true},
		{"docker compose up db redis", true},
		{"python manage.py runserver", false},
		{"pnpm dev", false},
		{"echo hello && docker compose logs", true},
	}
	for _, tt := range tests {
		got := IsComposeCommand(tt.shell)
		if got != tt.want {
			t.Errorf("IsComposeCommand(%q) = %v, want %v", tt.shell, got, tt.want)
		}
	}
}

func TestParseComposeFlags(t *testing.T) {
	shell := "docker compose -f docker-compose.dev.yml -f docker-compose.profiles.yml --profile temporal --profile azure up --pull always -d"
	flags := ParseComposeFlags(shell)
	if len(flags.Files) != 2 {
		t.Fatalf("expected 2 files, got %d", len(flags.Files))
	}
	if flags.Files[0] != "docker-compose.dev.yml" {
		t.Errorf("files[0]: got %s, want docker-compose.dev.yml", flags.Files[0])
	}
	if flags.Files[1] != "docker-compose.profiles.yml" {
		t.Errorf("files[1]: got %s, want docker-compose.profiles.yml", flags.Files[1])
	}
	if len(flags.Profiles) != 2 {
		t.Fatalf("expected 2 profiles, got %d", len(flags.Profiles))
	}
	if flags.Profiles[0] != "temporal" {
		t.Errorf("profiles[0]: got %s, want temporal", flags.Profiles[0])
	}
	if flags.Profiles[1] != "azure" {
		t.Errorf("profiles[1]: got %s, want azure", flags.Profiles[1])
	}
}

func TestParseComposeFlags_NoFlags(t *testing.T) {
	flags := ParseComposeFlags("docker compose up -d")
	if len(flags.Files) != 0 {
		t.Errorf("expected no files, got %d", len(flags.Files))
	}
	if len(flags.Profiles) != 0 {
		t.Errorf("expected no profiles, got %d", len(flags.Profiles))
	}
}

func TestStripComposeLogs(t *testing.T) {
	tests := []struct {
		name  string
		shell string
		want  string
	}{
		{
			name:  "hogli generated format",
			shell: "echo '▶ docker-compose: ...' && docker compose -f a.yml up --pull always -d && echo 'docker-compose ready' && docker compose -f a.yml logs --tail=100 -f",
			want:  "echo '▶ docker-compose: ...' && docker compose -f a.yml up --pull always -d && echo 'docker-compose ready' && tail -f /dev/null",
		},
		{
			name:  "no logs command",
			shell: "docker compose up -d",
			want:  "docker compose up -d",
		},
		{
			name:  "logs only",
			shell: "docker compose logs -f",
			want:  "tail -f /dev/null",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := StripComposeLogs(tt.shell)
			if got != tt.want {
				t.Errorf("StripComposeLogs:\n  got:  %q\n  want: %q", got, tt.want)
			}
		})
	}
}

func TestComposeFlags_PsArgs(t *testing.T) {
	flags := ComposeFlags{
		Files:    []string{"docker-compose.dev.yml", "docker-compose.profiles.yml"},
		Profiles: []string{"temporal"},
	}
	args := flags.PsArgs()
	want := []string{"compose", "-f", "docker-compose.dev.yml", "-f", "docker-compose.profiles.yml", "--profile", "temporal", "ps", "--format", "json", "-a"}
	if len(args) != len(want) {
		t.Fatalf("PsArgs: got %d args, want %d", len(args), len(want))
	}
	for i := range want {
		if args[i] != want[i] {
			t.Errorf("PsArgs[%d]: got %q, want %q", i, args[i], want[i])
		}
	}
}

func TestComposeFlags_LogArgs(t *testing.T) {
	flags := ComposeFlags{
		Files:    []string{"docker-compose.dev.yml"},
		Profiles: []string{"temporal", "azure"},
	}
	args := flags.LogArgs("db")
	want := []string{"compose", "-f", "docker-compose.dev.yml", "--profile", "temporal", "--profile", "azure", "logs", "--no-log-prefix", "--follow", "--tail", "100", "db"}
	if len(args) != len(want) {
		t.Fatalf("LogArgs: got %d args, want %d", len(args), len(want))
	}
	for i := range want {
		if args[i] != want[i] {
			t.Errorf("LogArgs[%d]: got %q, want %q", i, args[i], want[i])
		}
	}
}

func TestContainerIconChar(t *testing.T) {
	tests := []struct {
		state string
		want  string
	}{
		{"running", "●"},
		{"restarting", "◌"},
		{"exited", "✗"},
		{"created", "○"},
		{"unknown", "○"},
	}
	for _, tt := range tests {
		got := ContainerIconChar(Container{State: tt.state})
		if got != tt.want {
			t.Errorf("ContainerIconChar(state=%s): got %q, want %q", tt.state, got, tt.want)
		}
	}
}
