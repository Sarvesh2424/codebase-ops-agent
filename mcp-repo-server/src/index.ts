import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { simpleGit } from "simple-git";
import { z } from "zod";

const server = new McpServer({ name: "repo-server", version: "0.1.0" });
const git = simpleGit(process.env.REPO_PATH ?? process.cwd());

server.tool(
  "git_diff",
  "Get the diff of unstaged changes, optionally for one file",
  { file: z.string().nullish() },
  async ({ file }) => {
    const diff = await git.diff(file ? [file] : []);
    return { content: [{ type: "text", text: diff || "No changes." }] };
  },
);

await server.connect(new StdioServerTransport());
