package docker

import (
	"bufio"
	"encoding/json"
	"fmt"
	"image/color"
	"os"
	"os/exec"
	"sort"
	"strings"
	"sync"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
)

// DockerContainer represents a container from docker compose ps
type DockerContainer struct {
	Service string
	Status  string
	State   string
	Health  string
}

type ContainerListMsg struct {
	Containers []DockerContainer
}

type ContainerPollTickMsg struct{}

type ContainerLogLineMsg struct {
	Service string
	Line    string
}

// containerLogStream manages a log-following subprocess for a single container.
// Pointer-based so it survives Bubble Tea's value-copy Model updates.
type ContainerLogStream struct {
	mu      sync.Mutex
	cmd     *exec.Cmd
	stopped bool
}

func (s *ContainerLogStream) Stop() {
	if s == nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.stopped = true
	if s.cmd != nil && s.cmd.Process != nil {
		_ = s.cmd.Process.Kill()
	}
}

func IsDockerComposeShell(shell string) bool {
	return strings.Contains(shell, "docker compose") || strings.Contains(shell, "docker-compose")
}

func ParseComposeFile(shell string) string {
	parts := strings.Fields(shell)
	for i, p := range parts {
		if p == "-f" && i+1 < len(parts) {
			return parts[i+1]
		}
	}
	return ""
}

func composeBaseArgs(composeFile string) []string {
	if composeFile != "" {
		return []string{"compose", "-f", composeFile}
	}
	return []string{"compose"}
}

func FetchContainerList(composeFile string) tea.Cmd {
	return func() tea.Msg {
		base := composeBaseArgs(composeFile)
		args := append(base, "ps", "--format", "json", "-a")
		cmd := exec.Command("docker", args...)
		out, err := cmd.Output()
		if err != nil {
			return ContainerListMsg{}
		}
		var containers []DockerContainer
		for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
			if line == "" {
				continue
			}
			var raw struct {
				Service string `json:"Service"`
				Status  string `json:"Status"`
				State   string `json:"State"`
				Health  string `json:"Health"`
			}
			if json.Unmarshal([]byte(line), &raw) == nil {
				containers = append(containers, DockerContainer{
					Service: raw.Service,
					Status:  raw.Status,
					State:   raw.State,
					Health:  raw.Health,
				})
			}
		}
		sort.Slice(containers, func(i, j int) bool {
			return containers[i].Service < containers[j].Service
		})
		return ContainerListMsg{Containers: containers}
	}
}

func PollContainersTick() tea.Cmd {
	return tea.Tick(5*time.Second, func(time.Time) tea.Msg {
		return ContainerPollTickMsg{}
	})
}

const MaxContainerLogLines = 5000

func StartContainerLogStream(composeFile, service string, send func(tea.Msg)) *ContainerLogStream {
	stream := &ContainerLogStream{}
	base := composeBaseArgs(composeFile)
	args := append(base, "logs", "-f", "--tail=200", "--no-log-prefix", service)
	cmd := exec.Command("docker", args...)

	pr, pw, err := os.Pipe()
	if err != nil {
		return stream
	}
	cmd.Stdout = pw
	cmd.Stderr = pw

	if err := cmd.Start(); err != nil {
		_ = pr.Close()
		_ = pw.Close()
		return stream
	}

	stream.mu.Lock()
	stream.cmd = cmd
	stream.mu.Unlock()

	_ = pw.Close()

	go func() {
		scanner := bufio.NewScanner(pr)
		scanner.Buffer(make([]byte, 64*1024), 64*1024)
		for scanner.Scan() {
			stream.mu.Lock()
			stopped := stream.stopped
			stream.mu.Unlock()
			if stopped {
				break
			}
			send(ContainerLogLineMsg{
				Service: service,
				Line:    scanner.Text(),
			})
		}
		_ = pr.Close()
		_ = cmd.Wait()
	}()

	return stream
}

func RenderContainerStatusTable(containers []DockerContainer, width int) string {
	if len(containers) == 0 {
		return "  Waiting for containers..."
	}

	svcW := 7
	stateW := 5
	statusW := 6

	for _, c := range containers {
		if len(c.Service) > svcW {
			svcW = len(c.Service)
		}
		if len(c.State) > stateW {
			stateW = len(c.State)
		}
		if len(c.Status) > statusW {
			statusW = len(c.Status)
		}
	}

	maxSvcW := width / 3
	if maxSvcW > 0 && svcW > maxSvcW {
		svcW = maxSvcW
	}

	var sb strings.Builder
	sb.WriteByte('\n')
	header := fmt.Sprintf("  %-*s  %-*s  %s", svcW, "SERVICE", stateW, "STATE", "STATUS")
	sb.WriteString(lipgloss.NewStyle().Bold(true).Foreground(colorWhite).Render(header))
	sb.WriteByte('\n')

	sepLen := svcW + stateW + statusW + 8
	if sepLen > width-2 {
		sepLen = width - 2
	}
	if sepLen < 1 {
		sepLen = 1
	}
	sb.WriteString(lipgloss.NewStyle().Foreground(colorDarkGrey).Render("  " + strings.Repeat("─", sepLen)))
	sb.WriteByte('\n')

	for _, c := range containers {
		svc := c.Service
		runes := []rune(svc)
		if len(runes) > svcW {
			svc = string(runes[:svcW-1]) + "…"
		}

		var stateColor color.Color
		switch c.State {
		case "running":
			stateColor = colorGreen
		case "exited":
			stateColor = colorRed
		default:
			stateColor = colorYellow
		}

		sb.WriteString(fmt.Sprintf("  %-*s  ", svcW, svc))
		sb.WriteString(lipgloss.NewStyle().Foreground(stateColor).Render(fmt.Sprintf("%-*s", stateW, c.State)))
		sb.WriteString(lipgloss.NewStyle().Foreground(colorGrey).Render(fmt.Sprintf("  %s", c.Status)))
		if c.Health != "" {
			sb.WriteString(lipgloss.NewStyle().Foreground(colorGrey).Render(fmt.Sprintf("  (%s)", c.Health)))
		}
		sb.WriteByte('\n')
	}

	return sb.String()
}

func ContainerStateIcon(state string) string {
	switch state {
	case "running":
		return iconCharRunning
	case "exited":
		return iconCharCrashed
	case "paused":
		return iconCharPending
	default:
		return iconCharStopped
	}
}

func ContainerStateColor(state string) color.Color {
	switch state {
	case "running":
		return colorGreen
	case "exited":
		return colorRed
	case "paused":
		return colorYellow
	default:
		return colorGrey
	}
}

var (
	colorYellow   = lipgloss.Color("#F7A501")
	colorGrey     = lipgloss.Color("#9BA1B2")
	colorDarkGrey = lipgloss.Color("#3D3F43")
	colorGreen    = lipgloss.Color("#2DCC5D")
	colorRed      = lipgloss.Color("#F04438")
	colorWhite    = lipgloss.Color("#FFFFFF")
)

const (
	iconCharRunning = "●"
	iconCharPending = "◌"
	iconCharStopped = "○"
	iconCharCrashed = "✗"
)
