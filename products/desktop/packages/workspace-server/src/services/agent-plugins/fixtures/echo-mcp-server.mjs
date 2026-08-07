import readline from "node:readline";

const input = readline.createInterface({ input: process.stdin });

input.on("line", (line) => {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    process.exitCode = 1;
    input.close();
    return;
  }
  if (message.id === undefined) return;

  const result =
    message.method === "initialize"
      ? {
          protocolVersion: "2025-06-18",
          capabilities: { tools: {} },
          serverInfo: { name: "fixture", version: "1.0.0" },
        }
      : message.method === "tools/list"
        ? {
            tools: [
              {
                name: "echo",
                description: "Echo text",
                inputSchema: { type: "object" },
              },
            ],
          }
        : {};
  process.stdout.write(
    `${JSON.stringify({ jsonrpc: "2.0", id: message.id, result })}\n`,
  );
});
