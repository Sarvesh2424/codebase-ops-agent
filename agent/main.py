import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_groq import ChatGroq
from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage, SystemMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    plan: str
    findings: str
    verdict: str
    attempts: int
    notes: str


async def main():
    client = MultiServerMCPClient(
        {
            "repo": {
                "command": "npx",
                "args": ["tsx", "../mcp-repo-server/src/index.ts"],
                "transport": "stdio",
                "env": {"REPO_PATH": "/home/sarvesh/projects/whiteroom-frontend"},
            }
        }
    )
    tools = await client.get_tools()
    llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    tool_desc = "\n".join(f"- {t.name}: {t.description}" for t in tools)

    async def planner(state: State):
        msg = await llm.ainvoke(
            [
                SystemMessage(
                    f"Write a 2-4 step plan to answer the request using ONLY these tools:\n{tool_desc}\nDo not call tools."
                ),
                *state["messages"],
            ]
        )
        return {"plan": msg.content}

    async def investigator(state: State):
        system = SystemMessage(
            f"Follow this plan using the tools, then write concise findings. "
            f"Do not paste raw diffs unless the user asks for them.\nPlan:\n{state['plan']}"
        )
        resp = await llm_with_tools.ainvoke([system, *state["messages"]])
        return {"messages": [resp]}

    def after_investigator(state: State):
        return "tools" if state["messages"][-1].tool_calls else "reviewer"

    async def reviewer(state: State):
        findings = state["messages"][-1].content
        evidence = "\n\n".join(
            str(m.content)[:3000]
            for m in state["messages"]
            if isinstance(m, ToolMessage)
        )
        asks = "\n".join(
            str(m.content) for m in state["messages"] if isinstance(m, HumanMessage)
        )
        msg = await llm.ainvoke(
            [
                SystemMessage(
                    "First line: APPROVE or REJECT. REJECT if the findings claim anything not supported by the tool output, skip part of the plan, ignore any request in the user messages, or state guesses ('likely', 'presumably') as fact. If REJECT, say what is wrong."
                ),
                HumanMessage(
                    f"User messages:\n{asks}\n\nPlan:\n{state['plan']}\n\nTool output:\n{evidence}\n\nFindings:\n{findings}"
                ),
            ]
        )
        text = msg.content.strip()
        approved = text.upper().startswith("APPROVE")
        update = {
            "findings": findings,
            "notes": text,
            "verdict": "approve" if approved else "reject",
            "attempts": state["attempts"] + 1,
        }
        if not approved:
            update["messages"] = [
                HumanMessage(
                    f"Your findings were rejected: {text}\n"
                    "Rewrite the complete findings, fixing exactly that. Do not reply conversationally."
                )
            ]
        return update

    async def human_gate(state: State):
        decision = interrupt(
            {
                "findings": state["findings"],
                "reviewer_notes": state["notes"],
                "question": "Type 'yes' to accept, or give feedback",
            }
        )
        if str(decision).strip().lower() in ("yes", "y"):
            return {"verdict": "approved_by_human"}
        return {
            "verdict": "reject",
            "attempts": 0,
            "messages": [
                HumanMessage(
                    f"The user rejected your findings: {decision}\nRewrite the complete findings, fixing exactly that."
                )
            ],
        }

    def after_reviewer(state: State):
        if state["verdict"] == "approve" or state["attempts"] >= 2:
            return "human_gate"
        return "investigator"

    def after_human(state: State):
        return END if state["verdict"] == "approved_by_human" else "investigator"

    builder = StateGraph(State)
    builder.add_node("planner", planner)
    builder.add_node("investigator", investigator)
    builder.add_node("tools", ToolNode(tools))
    builder.add_node("reviewer", reviewer)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "investigator")
    builder.add_conditional_edges(
        "investigator", after_investigator, ["tools", "reviewer"]
    )
    builder.add_edge("tools", "investigator")
    builder.add_node("human_gate", human_gate)
    builder.add_conditional_edges(
        "reviewer", after_reviewer, ["human_gate", "investigator", END]
    )
    builder.add_conditional_edges("human_gate", after_human, ["investigator", END])
    agent = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "run-1"}}
    res = await agent.ainvoke(
        {"messages": "Summarize my uncommitted changes", "attempts": 0}, config
    )

    while "__interrupt__" in res:
        print(res["__interrupt__"][0].value["findings"])
        answer = input("\nAccept? (yes / feedback): ")
        res = await agent.ainvoke(Command(resume=answer), config)

    print("\nVERDICT:", res["verdict"])
    print("REVIEWER NOTES:", res.get("notes", ""))
    print(res["findings"])


asyncio.run(main())
