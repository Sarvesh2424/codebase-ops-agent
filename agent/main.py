import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_groq import ChatGroq
from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage,SystemMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END              
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    plan: str
    findings: str
    verdict: str
    attempts: int

async def main():
    client = MultiServerMCPClient({
        "repo": {
            "command": "npx",
            "args": ["tsx", "../mcp-repo-server/src/index.ts"],
            "transport": "stdio",
            "env": {"REPO_PATH": "/home/sarvesh/projects/whiteroom-frontend"},
        }
    })
    tools = await client.get_tools()
    llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    tool_desc = "\n".join(f"- {t.name}: {t.description}" for t in tools)

    async def planner(state: State):
        msg = await llm.ainvoke([
            SystemMessage(f"Write a 2-4 step plan to answer the request using ONLY these tools:\n{tool_desc}\nDo not call tools."),
            *state["messages"],
        ])
        return {"plan": msg.content}

    async def investigator(state: State):
        system = SystemMessage(f"Follow this plan using the tools, then write your findings.\nPlan:\n{state['plan']}")
        resp = await llm_with_tools.ainvoke([system, *state["messages"]])
        return {"messages": [resp]}

    def after_investigator(state: State):
        return "tools" if state["messages"][-1].tool_calls else "reviewer"

    async def reviewer(state: State):
        findings = state["messages"][-1].content
        evidence = "\n\n".join(str(m.content) for m in state["messages"] if isinstance(m, ToolMessage))[:6000]
        msg = await llm.ainvoke([
            SystemMessage("First line: APPROVE or REJECT. REJECT if the findings claim anything not supported by the tool output, or skip part of the plan. If REJECT, say what is unsupported."),
            HumanMessage(f"Plan:\n{state['plan']}\n\nTool output:\n{evidence}\n\nFindings:\n{findings}"),
        ])
        text = msg.content.strip()
        approved = text.upper().startswith("APPROVE")
        update = {"findings": findings, "verdict": "approve" if approved else "reject",
                "attempts": state["attempts"] + 1}
        if not approved:
            update["messages"] = [HumanMessage(f"Reviewer feedback: {text}")]
        return update

    def after_reviewer(state: State):
        if state["verdict"] == "approve" or state["attempts"] >= 2:
            return END
        return "investigator"

    builder = StateGraph(State)
    builder.add_node("planner", planner)
    builder.add_node("investigator", investigator)
    builder.add_node("tools", ToolNode(tools))
    builder.add_node("reviewer", reviewer)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "investigator")
    builder.add_conditional_edges("investigator", after_investigator, ["tools", "reviewer"])
    builder.add_edge("tools", "investigator")
    builder.add_conditional_edges("reviewer", after_reviewer, ["investigator", END])
    agent = builder.compile()
    res = await agent.ainvoke(
        {"messages": "Summarize my uncommitted changes and say who authored the last commit", "attempts": 0}
    )    
    print("PLAN:\n", res["plan"])
    print("\nVERDICT:", res["verdict"], f"(attempts: {res['attempts']})")
    print("\nFINDINGS:\n", res["findings"])

asyncio.run(main())