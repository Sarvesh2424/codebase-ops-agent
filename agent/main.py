import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_groq import ChatGroq
from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

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

    async def call_model(state: State):
        return {"messages": [await llm_with_tools.ainvoke(state["messages"])]}

    builder = StateGraph(State)
    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", tools_condition) 
    builder.add_edge("tools", "model")         
    agent = builder.compile()
    res = await agent.ainvoke({"messages": "Summarize my uncommitted changes"})
    print(res["messages"][-1].content)

asyncio.run(main())