import os
import time
from langchain_openai import ChatOpenAI
from langchain_community.tools import BraveSearch
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_ollama import ChatOllama

# 1. Set up the OpenRouter LLM
# We use ChatOpenAI but point the base_url to OpenRouter
#llm = ChatOpenAI(
#    base_url="https://openrouter.ai/api/v1",
#    api_key=os.environ.get("OPENROUTER_API_KEY"),
##    model="z-ai/glm-4.5-air:free",
#    model="tencent/hy3-preview:free"
#)
llm = ChatOllama(
    model="gemma4:latest",
    temperature=0,
    # Gemma 4 supports up to 32k-128k context, 
    # you can define it here:
    num_ctx=32768, 
)

# 2. Set up the News Search Tool
# This requires a BRAVE_API_KEY environment variable.
news_tool = BraveSearch.from_api_key(
    api_key=os.environ.get("BRAVE_API_KEY"), search_kwargs={"count": 20, "rich": True, "freshness": "pm"}
)
tools = [news_tool]

# Bind the tool to our OpenRouter model so it knows it can search
llm_with_tools = llm.bind_tools(tools)

def rate_limit_tool_call(state: MessagesState):
    """Small delay to respect free tier rate limits (Brave: 1 QPS)."""
    # If the last message was a tool call, wait a moment before executing
    last_message = state["messages"][-1]
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        time.sleep(1.1) 
    return state

# 3. Define the Nodes for LangGraph
def chatbot(state: MessagesState):
    """The main LLM node that processes the conversation state."""
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

# 4. Build the Graph
graph_builder = StateGraph(MessagesState)

# Add the agent node
graph_builder.add_node("chatbot", chatbot)

# Add the tools node (this executes the actual search when the LLM requests it)
tool_node = ToolNode(tools=[news_tool])
graph_builder.add_node("tools", tool_node)

# Add routing logic
graph_builder.add_edge(START, "chatbot")

# tools_condition automatically routes to "tools" if a tool call is made, otherwise to END
graph_builder.add_conditional_edges(
    "chatbot",
    tools_condition,
)

# After the tool runs, return to the chatbot to synthesize the final answer
graph_builder.add_edge("tools", "chatbot")

# Compile the graph into an executable application
app = graph_builder.compile()

# 5. Run the Application
if __name__ == "__main__":
    print("Welcome to the Investment News Agent!")
    company = input("Enter a company name or stock ticker to analyze (e.g., Apple, MSFT, Tesla): ").strip()
    if not company:
        company = "Alphabet (GOOGL)" # Default if you just press Enter
        
    user_query = (
        f"Analyze {company}. What is the current sentiment based on recent news? "
        f"Also, identify 3 to 4 key macroeconomic, industry, or company-specific aspects "
        f"likely to affect its stock price over the next few years. Search for data on those "
        f"specific aspects, and provide a detailed future outlook."
    )
    
    print(f"User: {user_query}\n")
    print("-" * 50)
    
    # System prompt forces the LLM into a "Plan and Execute" reasoning mode
    system_prompt = """<|turn>system<|think|> You are an elite financial analyst.
When asked to analyze a stock, you must:
1. Think step-by-step about what factors (macro, tech trends, competitors, etc.) drive this specific company's value.
2. Use your search tool MULTIPLE TIMES to gather info on the company AND those broader future factors.
3. Synthesize a comprehensive final report with a clear structure."""

    # Stream the events as they happen in the graph
    events = app.stream(
        {"messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_query)]},
        stream_mode="values"
    )
    
    for event in events:
        # Print the latest message added to the state
        event["messages"][-1].pretty_print()
