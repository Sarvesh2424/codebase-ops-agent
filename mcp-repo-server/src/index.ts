import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { simpleGit } from "simple-git";
import { z } from "zod";
import { readFile } from "node:fs/promises";
import path from "node:path";

const server = new McpServer({ name: "repo-server", version: "0.1.0" });
const git = simpleGit(process.env.REPO_PATH ?? process.cwd());

server.tool(
  "git_diff",
  "Get the diff of unstaged changes, optionally for one file",
  { file: z.string().nullish() },
  async ({ file }) => {
    const args = file
      ? ["--", file]
      : ["--", ".", ":(exclude)package-lock.json"];
    const diff = await git.diff(args);
    return { content: [{ type: "text", text: diff || "No changes." }] };
  },
);

server.tool(
  "git_status",
  "List staged, modified, deleted and untracked files",
  {},
  async () => {
    const s = await git.status();
    const out = {
      staged: s.staged,
      modified: s.modified,
      deleted: s.deleted,
      created: s.created,
      untracked: s.not_added,
    };
    return { content: [{ type: "text", text: JSON.stringify(out, null, 2) }] };
  },
);

server.tool(
  "git_diff_stats",
  "Exact lines added/removed per changed tracked file (unstaged)",
  {},
  async () => {
    const s = await git.diffSummary();
    const files = s.files.map((f) => ({
      file: f.file,
      insertions: "insertions" in f ? f.insertions : null,
      deletions: "deletions" in f ? f.deletions : null,
    }));
    const totals = files.reduce(
      (a, f) => ({
        insertions: a.insertions + (f.insertions ?? 0),
        deletions: a.deletions + (f.deletions ?? 0),
      }),
      { insertions: 0, deletions: 0 },
    );
    return {
      content: [
        { type: "text", text: JSON.stringify({ files, totals }, null, 2) },
      ],
    };
  },
);

server.tool(
  "count_lines",
  "Count lines in files. Use for untracked files. Paths are relative to the repo root.",
  { files: z.array(z.string()) },
  async ({ files }) => {
    const root = path.resolve(process.env.REPO_PATH ?? process.cwd());
    const out = [] as any[];
    for (const f of files) {
      const full = path.resolve(root, f);
      if (!full.startsWith(root + path.sep)) {
        out.push({ file: f, error: "outside repo" });
        continue;
      }
      try {
        const text = await readFile(full, "utf8");
        const lines = text.split("\n").length - (text.endsWith("\n") ? 1 : 0);
        out.push({ file: f, lines });
      } catch {
        out.push({ file: f, error: "unreadable" });
      }
    }
    const total = out.reduce((a, f) => a + ("lines" in f ? f.lines : 0), 0);
    return {
      content: [
        { type: "text", text: JSON.stringify({ files: out, total }, null, 2) },
      ],
    };
  },
);

await server.connect(new StdioServerTransport());
