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

server.tool(
  "git_status",
  "List staged, modified, deleted and untracked files",
  {},
  async () => {
    const s = await git.status();
    const out = { staged: s.staged, modified: s.modified, deleted: s.deleted, created: s.created, untracked: s.not_added };
    return { content: [{ type: "text", text: JSON.stringify(out, null, 2) }] };
  }
);

await server.connect(new StdioServerTransport());
