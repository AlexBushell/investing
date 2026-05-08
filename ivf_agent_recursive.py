import os
import time
import json
import re
from typing import TypedDict, List, Optional, Dict, Annotated
from langchain_community.tools import BraveSearch
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage, ToolMessage
from langgraph.graph import StateGraph, START, END, add_messages
from langchain_ollama import ChatOllama

# ──────────────────────────────────────────────
# 1. Configuration
# ──────────────────────────────────────────────

llm = ChatOllama(
    model="gemma4:latest",
    temperature=0,
    num_ctx=131072,  # 128K context
)

_brave_api_key = os.environ.get("BRAVE_API_KEY")
if not _brave_api_key:
    raise EnvironmentError("BRAVE_API_KEY environment variable is not set")

news_tool = BraveSearch.from_api_key(
    api_key=_brave_api_key, search_kwargs={"count": 20, "rich": True, "freshness": "pm"}
)

tools = [news_tool]
llm_with_tools = llm.bind_tools(tools)

MAX_DEPTH = 5
MATERIALITY_THRESHOLD = 3
MAX_TOOL_ROUNDS = 5
MAX_TOTAL_WEAKNESSES = 50

# ──────────────────────────────────────────────
# 2. State Definitions
# ──────────────────────────────────────────────

class WeaknessNode(TypedDict):
    id: str                               # e.g. "W1", "W1-1", "W1-2-3"
    parent_id: Optional[str]              # None for root-level weaknesses
    topic: str                            # Short label
    description: str                      # Detailed description of the weakness/gap
    materiality_score: int                # 1-5
    deep_analysis: Optional[str]          # Populated after deep dive
    child_weaknesses: List[str]           # IDs of discovered sub-weaknesses
    depth_level: int                      # 1-based, max MAX_DEPTH
    explored: bool                        # Has this been deep-dived?

class AgentState(TypedDict):
    company: str
    messages: Annotated[List[BaseMessage], add_messages]
    initial_analysis: Optional[str]
    weakness_stack: List[str]             # priority stack: IDs pending deep dive
    all_weaknesses: Dict[str, WeaknessNode]
    finalized_weaknesses: List[str]       # IDs of fully explored nodes
    current_weakness_id: Optional[str]    # ID currently being deep-dived
    final_synthesis: Optional[str]
    depth_reached: bool                   # True if any branch hit max depth
    max_depth_hit_at: Optional[str]       # Which weakness ID triggered truncation

# ──────────────────────────────────────────────
# 3. Base System Prompt
# ──────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """ROLE: You are an elite financial analyst with deep expertise in fundamental analysis, macroeconomic forecasting, industry research, and investment thesis development.

CORE PRINCIPLES:
1. Think step-by-step before each response. Show your reasoning.
2. Be intellectually honest about uncertainties and unknown factors.
3. Clearly distinguish between confirmed facts, consensus views, and informed speculation.
4. Assign materiality scores consistently using the provided rubric.
5. Be thorough and precise. Superficial analysis is unacceptable.

MATERIALITY SCORING RUBRIC:
5 (Critical) — Could fundamentally alter the company's viability, business model, or long-term survival. Examples: existential regulatory threat, technology disruption making core product obsolete, solvency risk.
4 (Major) — Likely to significantly impact financial performance, valuation, or competitive position (>15% impact). Examples: major lawsuit, key market downturn, critical supplier concentration.
3 (Notable) — Material risk that warrants careful monitoring and could meaningfully affect the investment case (5-15% impact). Examples: moderate competitive pressure, regulatory uncertainty, cyclical headwinds.
2 (Minor) — Limited impact on investment thesis (<5% impact). Low probability of materialization. Examples: minor legal proceedings, routine leadership changes, small market fluctuations.
1 (Negligible) — Background noise with very low relevance to the investment decision. Not worth further analysis.

EXECUTION FRAMEWORK:
You operate in a recursive analysis loop. You will be guided through specific phases:
- PHASE 1 (Initial Analysis): Broad research covering company, macro, industry, and competitive factors.
- PHASE 2 (Identify Weaknesses): Extract gaps, uncertainties, and risks from the analysis.
- PHASE 3 (Deep Dive): Thoroughly investigate a specific weakness area.
- PHASE 4 (Reflect): After each deep dive, identify whether new sub-weaknesses have emerged.
- PHASE 5 (Synthesize): Combine all findings into a comprehensive investment case.

Follow the phase instructions you receive precisely. Use the Brave Search tool whenever you need to gather current data."""

# ──────────────────────────────────────────────
# 4. Structured Output Parsing
# ──────────────────────────────────────────────

def parse_materiality_score(value) -> int:
    """Robustly parse a materiality score from various possible LLM outputs."""
    if isinstance(value, int):
        return max(1, min(5, value))
    if isinstance(value, float):
        return max(1, min(5, int(value)))
    if isinstance(value, str):
        # Handle strings like "4", "4/5", "High", "3.5"
        value = value.strip().lower()
        # Remove trailing "/5" or "/10"
        value = re.sub(r'/\d+', '', value)
        # Remove percent signs
        value = value.replace('%', '')
        # Check for words
        word_map = {"critical": 5, "high": 4, "major": 4, "notable": 3, "medium": 3, "minor": 2, "low": 2, "negligible": 1}
        if value in word_map:
            return word_map[value]
        # Try numeric
        try:
            return max(1, min(5, int(float(value))))
        except (ValueError, TypeError):
            pass
    return 3  # Safe default


def parse_weakness_json(text: str) -> Optional[Dict]:
    """Extract a JSON object with a 'weaknesses' key from LLM output."""
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_match = re.search(r'\{[\s\S]*"weaknesses"[\s\S]*\}', text)
        if json_match:
            json_str = json_match.group(0)
        else:
            return None
    
    try:
        data = json.loads(json_str)
        if "weaknesses" in data and isinstance(data["weaknesses"], list):
            validated = []
            for w in data["weaknesses"]:
                if isinstance(w, dict) and all(k in w for k in ("topic", "description", "materiality_score")):
                    w["materiality_score"] = parse_materiality_score(w["materiality_score"])
                    validated.append(w)
            return {"weaknesses": validated}
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def generate_weakness_id(parent_id: Optional[str], existing_ids: set) -> str:
    """Generate a unique weakness ID following the tree naming scheme."""
    if parent_id is None:
        existing_root = [int(id[1:]) for id in existing_ids if re.match(r'^W\d+$', id)]
        next_num = max(existing_root) + 1 if existing_root else 1
        return f"W{next_num}"
    else:
        children = [id for id in existing_ids if id.startswith(parent_id + "-")]
        if not children:
            return f"{parent_id}-1"
        else:
            suffixes = [int(id.split("-")[-1]) for id in children if id.split("-")[-1].isdigit()]
            next_num = max(suffixes) + 1 if suffixes else 1
            return f"{parent_id}-{next_num}"


# ──────────────────────────────────────────────
# 5. Tool Execution Helper
# ──────────────────────────────────────────────

def _execute_tool_calls(messages: List[BaseMessage]) -> List[BaseMessage]:
    """Execute any pending tool calls in the last message and append results."""
    result_messages = list(messages)
    for _ in range(MAX_TOOL_ROUNDS):
        response = llm_with_tools.invoke(result_messages)
        result_messages.append(response)

        if not hasattr(response, 'tool_calls') or not response.tool_calls:
            return result_messages

        for tc in response.tool_calls:
            time.sleep(1.1)  # 1 QPS Brave API rate limit
            try:
                args = tc["args"]
                tool_input = args.get("query", str(args)) if isinstance(args, dict) else str(args)
                tool_result = news_tool.invoke(tool_input)
            except Exception as e:
                tool_result = f"Error executing search: {e}"

            result_messages.append(
                ToolMessage(content=str(tool_result), tool_call_id=tc["id"])
            )

    # Rounds exhausted with tool calls still pending — do one final synthesis pass
    # so callers always receive an LLM text response as the last message.
    final_response = llm_with_tools.invoke(result_messages)
    result_messages.append(final_response)
    return result_messages


def _extract_content(response) -> str:
    """Safely extract text content from an LLM response."""
    if hasattr(response, 'content') and response.content is not None:
        return str(response.content)
    if hasattr(response, 'text') and response.text is not None:
        return str(response.text)
    return str(response)


def _prune_messages(messages: List[BaseMessage], max_recent: int = 10) -> List[BaseMessage]:
    """Prune message history to keep context manageable.
    
    Fix for Issue #4: With add_messages, every tool call and search result
    accumulates in the history. This prunes old tool exchanges while keeping
    system prompt and key context.
    """
    if len(messages) <= max_recent:
        return messages
    
    # Keep the system prompt (first message) and the most recent messages
    kept = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            kept.append(msg)
            break
    
    # Keep the last max_recent - 1 messages (or all if we have fewer)
    tail_start = max(len(messages) - (max_recent - 1), 0)
    # Make sure we don't re-add the system message
    tail = [m for m in messages[tail_start:] if not isinstance(m, SystemMessage)]
    
    return kept + tail


def _register_weaknesses(
    parsed_weaknesses: List[Dict],
    state: AgentState,
    parent_id: Optional[str],
    new_depth: int,
    enforce_truncation: bool,
) -> None:
    """Register parsed weakness dicts into state, respecting depth and width limits."""
    if "all_weaknesses" not in state:
        state["all_weaknesses"] = {}
    if "weakness_stack" not in state:
        state["weakness_stack"] = []

    existing_ids = set(state["all_weaknesses"].keys())

    for w_data in parsed_weaknesses:
        if len(state["all_weaknesses"]) >= MAX_TOTAL_WEAKNESSES:
            break

        score = parse_materiality_score(w_data["materiality_score"])
        depth = MAX_DEPTH if enforce_truncation else new_depth

        if enforce_truncation:
            score = min(2, score)
            state["depth_reached"] = True

        wid = generate_weakness_id(parent_id, existing_ids)
        existing_ids.add(wid)

        if enforce_truncation and not state.get("max_depth_hit_at"):
            state["max_depth_hit_at"] = wid

        state["all_weaknesses"][wid] = {
            "id": wid,
            "parent_id": parent_id,
            "topic": w_data["topic"],
            "description": w_data["description"],
            "materiality_score": score,
            "deep_analysis": None,
            "child_weaknesses": [],
            "depth_level": depth,
            "explored": False,
        }

        if parent_id and parent_id in state["all_weaknesses"]:
            state["all_weaknesses"][parent_id]["child_weaknesses"].append(wid)

        if score >= MATERIALITY_THRESHOLD and not enforce_truncation:
            state["weakness_stack"].append(wid)


# ──────────────────────────────────────────────
# 6. Build State Summary (for context management)
# ──────────────────────────────────────────────

def build_tree_summary(all_weaknesses: Dict[str, WeaknessNode]) -> str:
    """Build a condensed textual summary of the weakness tree explored so far."""
    if not all_weaknesses:
        return "(No weaknesses identified yet.)"
    
    lines = ["=== WEAKNESS TREE EXPLORATION SUMMARY ==="]
    
    def render_node(node_id: str, indent: int = 0):
        node = all_weaknesses.get(node_id)
        if not node:
            return
        prefix = "  " * indent
        explored_mark = " [EXPLORED]" if node["explored"] else " [PENDING]"
        score_label = f"M:{node['materiality_score']}"
        lines.append(f"{prefix}{node['id']} ({score_label}, depth {node['depth_level']}{explored_mark}): {node['topic']}")
        lines.append(f"{prefix}  → {node['description'][:200]}...")
        for child_id in node["child_weaknesses"]:
            render_node(child_id, indent + 1)
    
    root_ids = [wid for wid, node in all_weaknesses.items() if node["parent_id"] is None]
    root_ids.sort()
    for rid in root_ids:
        render_node(rid)
    
    return "\n".join(lines)


def build_analysis_archive(finalized: List[str], all_weaknesses: Dict[str, WeaknessNode]) -> str:
    """Build a summary of all finalized (deep-dived) weaknesses and their analysis."""
    if not finalized:
        return "(No deep analyses completed yet.)"
    
    sections = ["=== COMPLETED DEEP ANALYSES ==="]
    for wid in finalized:
        node = all_weaknesses.get(wid)
        if node and node["deep_analysis"]:
            sections.append(f"\n--- {node['id']}: {node['topic']} (M:{node['materiality_score']}, depth {node['depth_level']}) ---")
            analysis = node["deep_analysis"]
            if len(analysis) > 500:
                analysis = analysis[:500] + "... [truncated for context]"
            sections.append(analysis)
    
    return "\n".join(sections)


# ──────────────────────────────────────────────
# 7. Node Functions
# ──────────────────────────────────────────────

def initial_analyst_node(state: AgentState) -> AgentState:
    """Phase 1: Broad initial research and analysis.
    
    Uses the tool execution helper which loops LLM -> tools -> LLM
    until the LLM produces a content-rich response with search data.
    """
    company = state["company"]
    
    prompt = (
        f"=== PHASE 1: INITIAL ANALYSIS ===\n"
        f"Company to analyze: {company}\n\n"
        f"TASK:\n"
        f"Conduct a thorough first-pass analysis of {company}. You must use the Brave Search tool MULTIPLE TIMES to gather information on the following dimensions:\n\n"
        f"1. COMPANY FUNDAMENTALS: Revenue, earnings, margins, growth trajectory, debt, cash flow, valuation multiples.\n"
        f"2. MACROECONOMIC CONTEXT: Interest rates, inflation, GDP growth, currency impacts relevant to this company.\n"
        f"3. INDUSTRY & COMPETITIVE LANDSCAPE: Market position, market share trends, key competitors, barriers to entry.\n"
        f"4. TECHNOLOGICAL & REGULATORY FACTORS: Disruption risks, regulatory headwinds/tailwinds, patent/IP considerations.\n"
        f"5. CATALYSTS & RISKS: Upcoming events, earnings catalysts, known risk factors.\n\n"
        f"OUTPUT FORMAT:\n"
        f"Produce a comprehensive initial research memo with clear sections for each dimension above. "
        f"Be specific with numbers, dates, and named entities. Identify your confidence level for each claim "
        f"(High/Medium/Low). At the end, list the 3-5 most important open questions or uncertainties "
        f"that need deeper investigation.\n\n"
        f"Search multiple times — do not rely on a single query. Each search should target a specific dimension.\n\n"
        f"IMPORTANT: After you receive search results, synthesize them into a thorough analysis. "
        f"Do NOT make additional searches after you have enough data — proceed to write the analysis."
    )
    
    seed_messages = [
        SystemMessage(content=BASE_SYSTEM_PROMPT),
        HumanMessage(content=prompt)
    ]
    
    # Execute LLM with full tool loop (searches, results, synthesis)
    final_messages = _execute_tool_calls(seed_messages)
    
    # Extract the final content response
    final_response = final_messages[-1]
    initial_text = _extract_content(final_response)
    
    # Prune and store messages for context management
    state["messages"] = _prune_messages(final_messages, max_recent=8)
    state["initial_analysis"] = initial_text
    
    return state


def identify_weaknesses_node(state: AgentState) -> AgentState:
    """Phase 2: Extract weaknesses, uncertainties, and gaps from the latest analysis."""
    latest_text = None
    current_wid = state.get("current_weakness_id")

    if current_wid and current_wid in state.get("all_weaknesses", {}):
        node = state["all_weaknesses"][current_wid]
        if node.get("deep_analysis"):
            latest_text = node["deep_analysis"]

    if not latest_text:
        latest_text = state.get("initial_analysis", "")

    if not latest_text:
        return state

    tree_summary = build_tree_summary(state.get("all_weaknesses", {}))
    archive = build_analysis_archive(state.get("finalized_weaknesses", []), state.get("all_weaknesses", {}))

    depth_context = ""
    if current_wid and current_wid in state.get("all_weaknesses", {}):
        parent_node = state["all_weaknesses"][current_wid]
        current_depth = parent_node["depth_level"]
        if current_depth >= MAX_DEPTH:
            depth_context = (
                f"IMPORTANT: You are at depth {current_depth}, which is the maximum allowed depth ({MAX_DEPTH}). "
                f"Any new weaknesses you identify MUST be assigned a materiality_score of 1 or 2 — "
                f"they will NOT be further explored. Simply note them for the final synthesis."
            )
        else:
            depth_context = f"You are at depth {current_depth}. Sub-weaknesses will be at depth {current_depth + 1}."

    if len(latest_text) > 8000:
        latest_text = latest_text[:8000] + "\n\n... [analysis truncated for context window management]"

    prompt = (
        f"=== PHASE 2: IDENTIFY WEAKNESSES ===\n\n"
        f"TASK:\n"
        f"Review the analysis provided below and identify weaknesses, knowledge gaps, uncertainties, "
        f"or risks within it. These are areas where:\n"
        f"- The data or evidence is insufficient or contradictory\n"
        f"- Assumptions need further validation\n"
        f"- Alternative scenarios or outcomes are not fully considered\n"
        f"- The analysis relies on uncertain forecasts or estimates\n"
        f"- There are known unknowns that could materially change the investment case\n\n"
        f"ANALYSIS TO REVIEW:\n"
        f"---\n{latest_text}\n---\n\n"
        f"EXISTING WEAKNESS TREE (for context — avoid duplicating already-identified weaknesses):\n"
        f"---\n{tree_summary}\n---\n\n"
        f"{archive}\n\n"
        f"{depth_context}\n\n"
        f"OUTPUT FORMAT:\n"
        f"Return ONLY a valid JSON object with a single key \"weaknesses\" containing an array of objects. "
        f"Each object must have exactly these fields:\n"
        f"- \"topic\": A short 2-5 word label for the weakness\n"
        f"- \"description\": A detailed 1-3 sentence explanation of the weakness\n"
        f"- \"materiality_score\": An integer 1-5 following the materiality rubric\n\n"
        f"```json\n{{\n  \"weaknesses\": [\n    {{\n      \"topic\": \"Revenue concentration risk\",\n      \"description\": \"60% of revenue comes from 3 customers. Loss of any one could materially impact earnings.\",\n      \"materiality_score\": 4\n    }}\n  ]\n}}\n```\n\n"
        f"If there are ZERO weaknesses with materiality_score >= 3, return an empty array: {{\"weaknesses\": []}}\n\n"
        f"IMPORTANT: Do NOT use the Brave Search tool here. This is purely an analytical review of existing data."
    )

    state["messages"].append(HumanMessage(content=prompt))
    state["messages"] = _prune_messages(state["messages"], max_recent=12)
    response = llm.invoke(state["messages"])
    state["messages"].append(response)

    parsed = parse_weakness_json(_extract_content(response))

    if not parsed:
        retry_prompt = (
            "I could not parse your previous response as valid JSON. "
            "Please return ONLY the following exact JSON format with no additional text:\n\n"
            '{"weaknesses": [{"topic": "...", "description": "...", "materiality_score": 3}]}\n\n'
            "If there are no weaknesses, return: {\"weaknesses\": []}\n"
            "Do not include any other text or markdown formatting."
        )
        state["messages"].append(HumanMessage(content=retry_prompt))
        retry_response = llm.invoke(state["messages"])
        state["messages"].append(retry_response)
        parsed = parse_weakness_json(_extract_content(retry_response))

    parent_id = state.get("current_weakness_id")
    parent_depth = 0
    if parent_id and parent_id in state.get("all_weaknesses", {}):
        parent_depth = state["all_weaknesses"][parent_id]["depth_level"]

    new_depth = parent_depth + 1
    enforce_truncation = new_depth > MAX_DEPTH

    if parsed and parsed["weaknesses"]:
        _register_weaknesses(parsed["weaknesses"], state, parent_id, new_depth, enforce_truncation)

    return state


def dequeue_next_weakness_node(state: AgentState) -> AgentState:
    """Pop the next weakness from the stack and set it as current."""
    stack = state.get("weakness_stack", [])
    if not stack:
        state["current_weakness_id"] = None
        return state
    
    weakness_nodes = [(wid, state["all_weaknesses"].get(wid, {}).get("materiality_score", 0)) for wid in stack]
    weakness_nodes.sort(key=lambda x: (-x[1], state["all_weaknesses"].get(x[0], {}).get("depth_level", 0)))
    
    next_wid = weakness_nodes[0][0]
    stack.remove(next_wid)
    state["weakness_stack"] = stack
    state["current_weakness_id"] = next_wid
    
    return state


def deep_dive_node(state: AgentState) -> AgentState:
    """Phase 3: Perform a focused deep dive into the current weakness.
    
    Uses the tool execution helper to search, get results, and synthesize.
    """
    wid = state.get("current_weakness_id")
    if not wid or wid not in state.get("all_weaknesses", {}):
        return state
    
    node = state["all_weaknesses"][wid]
    
    parent_context = ""
    parent_id = node.get("parent_id")
    if parent_id and parent_id in state["all_weaknesses"]:
        parent_node = state["all_weaknesses"][parent_id]
        parent_context = f"PARENT ANALYSIS CONTEXT:\nTopic: {parent_node['topic']}\nKey insight: {parent_node['deep_analysis'][:1000] if parent_node.get('deep_analysis') else parent_node['description']}\n\n"
    
    tree_context = build_tree_summary(state.get("all_weaknesses", {}))
    archive_context = build_analysis_archive(state.get("finalized_weaknesses", []), state.get("all_weaknesses", {}))
    
    prompt = (
        f"=== PHASE 3: DEEP DIVE ANALYSIS ===\n\n"
        f"WEAKNESS ID: {wid}\n"
        f"TOPIC: {node['topic']}\n"
        f"MATERIALITY SCORE: {node['materiality_score']}/5\n"
        f"DEPTH LEVEL: {node['depth_level']}/{MAX_DEPTH}\n\n"
        f"DESCRIPTION OF WEAKNESS TO INVESTIGATE:\n"
        f"{node['description']}\n\n"
        f"{parent_context}"
        f"TREE CONTEXT:\n{tree_context}\n\n"
        f"{archive_context}\n\n"
        f"TASK:\n"
        f"Conduct a thorough investigation into this specific analytical weakness. "
        f"You MUST use the Brave Search tool MULTIPLE TIMES to find:\n\n"
        f"1. SPECIFIC EVIDENCE: Find concrete data, reports, news articles addressing this weakness.\n"
        f"2. CONTRASTING VIEWS: Search for perspectives that disagree with or complicate the analysis.\n"
        f"3. QUANTITATIVE IMPACT: Estimate the potential financial impact (in dollar terms or percentage).\n"
        f"4. SCENARIO ANALYSIS: Consider best case, base case, and worst case outcomes.\n"
        f"5. TIMELINE: When would this risk/uncertainty materialize? What are the triggers?\n\n"
        f"OUTPUT REQUIREMENTS:\n"
        f"- Provide specific data points with sources\n"
        f"- Rate your confidence in each major finding (High/Medium/Low)\n"
        f"- Identify any assumptions you are making\n"
        f"- Be intellectually honest about what you cannot know\n"
        f"- Length: comprehensive (500-2000 words)\n"
        f"- End with a brief summary of the single most important implication for the investment case\n\n"
        f"IMPORTANT: After you receive search results, synthesize them into your analysis. "
        f"Do NOT make additional searches after you have enough data."
    )
    
    # Build seed messages — reuse existing conversation context plus this prompt
    seed_messages = list(state.get("messages", []))
    seed_messages.append(HumanMessage(content=prompt))
    # Prune before the tool loop to keep context focused on this deep dive
    seed_messages = _prune_messages(seed_messages, max_recent=6)
    
    # Execute LLM with full tool loop (searches, results, synthesis)
    final_messages = _execute_tool_calls(seed_messages)
    
    # Extract the final content
    final_response = final_messages[-1]
    analysis_text = _extract_content(final_response)
    
    # Store analysis back into the weakness node
    if "all_weaknesses" not in state:
        state["all_weaknesses"] = {}
    state["all_weaknesses"][wid]["deep_analysis"] = analysis_text
    state["all_weaknesses"][wid]["explored"] = True
    
    if "finalized_weaknesses" not in state:
        state["finalized_weaknesses"] = []
    state["finalized_weaknesses"].append(wid)
    
    # Update messages with the pruned tool loop result
    state["messages"] = _prune_messages(final_messages, max_recent=8)
    
    return state


def reflect_node(state: AgentState) -> AgentState:
    """Phase 4: After a deep dive, reflect to identify new sub-weaknesses."""
    wid = state.get("current_weakness_id")
    if not wid or wid not in state.get("all_weaknesses", {}):
        return state
    
    node = state["all_weaknesses"][wid]
    analysis = node.get("deep_analysis", "")
    
    if not analysis:
        return state
    
    tree_summary = build_tree_summary(state.get("all_weaknesses", {}))
    archive = build_analysis_archive(state.get("finalized_weaknesses", []), state.get("all_weaknesses", {}))
    
    depth_note = ""
    if node["depth_level"] >= MAX_DEPTH:
        depth_note = (
            f"NOTE: You are at maximum depth ({MAX_DEPTH}). Any weaknesses you identify will NOT be "
            f"further explored — simply catalog them for the final synthesis. Assign them all "
            f"materiality_score of 1 or 2."
        )
    else:
        depth_note = (
            f"Current depth: {node['depth_level']}. Sub-weaknesses you identify will be at depth "
            f"{node['depth_level'] + 1} and may be explored in subsequent iterations."
        )
    
    prompt = (
        f"=== PHASE 4: REFLECTION ON DEEP DIVE ===\n\n"
        f"You have just completed a deep dive analysis into:\n"
        f"WEAKNESS: {node['topic']} (M:{node['materiality_score']}/5, depth {node['depth_level']})\n\n"
        f"COMPLETED ANALYSIS:\n"
        f"---\n{analysis[:6000]}\n---\n\n"
        f"{tree_summary}\n\n"
        f"{archive}\n\n"
        f"{depth_note}\n\n"
        f"TASK:\n"
        f"Critically reflect on the deep dive analysis you just produced. Ask yourself:\n\n"
        f"1. Does this analysis reveal NEW uncertainties or risks that were not apparent before?\n"
        f"2. Were there assumptions in the analysis that need further validation?\n"
        f"3. Did you encounter conflicting data or contradictory evidence?\n"
        f"4. Are there second-order effects or downstream consequences of this weakness?\n"
        f"5. Is there a deeper root cause that hasn't been fully explored?\n\n"
        f"OUTPUT FORMAT:\n"
        f"Return ONLY a valid JSON object with a single key \"weaknesses\" containing an array of objects. "
        f"Each object must have: \"topic\", \"description\", and \"materiality_score\" (1-5).\n\n"
        f"```json\n{{\n  \"weaknesses\": [\n    {{\n      \"topic\": \"Sub-weakness label\",\n      \"description\": \"Detailed description of this newly discovered weakness\",\n      \"materiality_score\": 3\n    }}\n  ]\n}}\n```\n\n"
        f"If no new material weaknesses (score >= 3) are discovered, return: {{\"weaknesses\": []}}\n\n"
        f"IMPORTANT: Do NOT use the Brave Search tool here. This is purely reflection on existing analysis."
    )
    
    state["messages"].append(HumanMessage(content=prompt))
    state["messages"] = _prune_messages(state["messages"], max_recent=10)
    response = llm.invoke(state["messages"])
    state["messages"].append(response)
    
    result_text = _extract_content(response)
    parsed = parse_weakness_json(result_text)
    
    if parsed and parsed["weaknesses"]:
        new_depth = node["depth_level"] + 1
        enforce_truncation = new_depth > MAX_DEPTH
        _register_weaknesses(parsed["weaknesses"], state, wid, new_depth, enforce_truncation)

    return state


def synthesize_node(state: AgentState) -> AgentState:
    """Phase 5: Synthesize all findings into a comprehensive investment case."""
    company = state["company"]
    initial = state.get("initial_analysis", "(No initial analysis available)")
    finalized = state.get("finalized_weaknesses", [])
    all_weaknesses = state.get("all_weaknesses", {})
    depth_reached = state.get("depth_reached", False)
    max_depth_hit = state.get("max_depth_hit_at", "N/A")
    
    tree_summary = build_tree_summary(all_weaknesses)
    archive = build_analysis_archive(finalized, all_weaknesses)
    
    unexamined = []
    for wid, node in all_weaknesses.items():
        if not node["explored"]:
            unexamined.append(node)
    
    unexamined_block = ""
    if unexamined:
        unexamined_block = "\n=== UNEXAMINED WEAKNESSES (materiality < 3, not deep-dived) ===\n"
        for node in sorted(unexamined, key=lambda n: (-n["materiality_score"], n["depth_level"])):
            unexamined_block += f"- {node['id']} ({node['topic']}, M:{node['materiality_score']}, depth {node['depth_level']}): {node['description'][:200]}\n"
    
    depth_report = (
        f"=== ANALYSIS DEPTH REPORT ===\n"
        f"Maximum allowed depth: {MAX_DEPTH}\n"
        f"Maximum depth reached: {'Yes' if depth_reached else 'No'}"
    )
    if max_depth_hit != "N/A":
        depth_report += f"\nFirst truncation occurred at: {max_depth_hit}"
    
    prompt = (
        f"=== PHASE 5: FINAL SYNTHESIS ===\n\n"
        f"COMPANY: {company}\n\n"
        f"TASK:\n"
        f"Produce a comprehensive, professional-grade investment case for {company} by synthesizing "
        f"all of the research and analysis conducted across the entire recursive weakness exploration. "
        f"This represents the culmination of a multi-level analysis that explored weaknesses at up to "
        f"{MAX_DEPTH} levels of depth.\n\n"
        f"INITIAL ANALYSIS (broad research):\n"
        f"---\n{initial[:5000]}\n---\n\n"
        f"COMPLETED DEEP ANALYSES ({len(finalized)} areas explored in depth):\n"
        f"---\n{archive}\n---\n\n"
        f"{unexamined_block}\n\n"
        f"{depth_report}\n\n"
        f"REQUIRED OUTPUT STRUCTURE:\n\n"
        f"# INVESTMENT CASE: {company}\n\n"
        f"## 1. COMPANY SUMMARY\n"
        f"[Brief overview of the company, its business model, and market position]\n\n"
        f"## 2. WEAKNESS TREE OVERVIEW\n"
        f"[Hierarchical visualization or structured list of all weaknesses identified, "
        f"organized by materiality score. Include the full tree from the summary above.]\n\n"
        f"## 3. TOP-RISK DEEP DIVES\n"
        f"[For the 3-5 highest materiality weaknesses explored, provide concise summaries "
        f"of the deep dive findings. Include key data points, scenario analysis, and confidence levels.]\n\n"
        f"## 4. INVESTMENT THESIS\n"
        f"[Synthesize ALL findings — positive and negative — into a balanced investment thesis. "
        f"Include: bull case, bear case, and base case with probabilities. "
        f"Address how each explored weakness modifies the thesis.]\n\n"
        f"## 5. KEY MONITORING POINTS\n"
        f"[Specific metrics, events, or triggers to watch that would either confirm or resolve "
        f"the key weaknesses identified. Include timelines where relevant.]\n\n"
        f"## 6. METHODOLOGY NOTE\n"
        f"[Explain that this analysis used a recursive weakness tree approach, exploring "
        f"weaknesses to {'a maximum depth of ' + str(MAX_DEPTH) + ' levels' if depth_reached else 'exhaustion of all material weaknesses'}.\n"
        f"Include the depth report.]\n\n"
        f"CRITICAL REQUIREMENTS:\n"
        f"- Be thorough and specific. Avoid generic statements.\n"
        f"- Distinguish clearly between facts, consensus views, and your own analysis.\n"
        f"- Acknowledge remaining uncertainties and their potential impact.\n"
        f"- The tone should be professional, analytical, and balanced.\n"
        f"- This is a substantial document — aim for 2000-5000 words."
    )
    
    # Synthesis may benefit from a search for latest data
    seed_messages = [SystemMessage(content=BASE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    final_messages = _execute_tool_calls(seed_messages)
    final_response = final_messages[-1]
    synthesis = _extract_content(final_response)
    state["final_synthesis"] = synthesis
    
    return state


# ──────────────────────────────────────────────
# 8. Conditional Routing Logic
# ──────────────────────────────────────────────

def route_after_identify(state: AgentState) -> str:
    """After identifying weaknesses, check if stack has items to process."""
    stack = state.get("weakness_stack", [])
    if stack:
        return "dequeue_next_weakness"
    else:
        return "synthesize"


# ──────────────────────────────────────────────
# 9. Graph Construction
# ──────────────────────────────────────────────

graph_builder = StateGraph(AgentState)

# Add nodes
graph_builder.add_node("initial_analyst", initial_analyst_node)
graph_builder.add_node("identify_weaknesses", identify_weaknesses_node)
graph_builder.add_node("dequeue_next_weakness", dequeue_next_weakness_node)
graph_builder.add_node("deep_dive", deep_dive_node)
graph_builder.add_node("reflect", reflect_node)
graph_builder.add_node("synthesize", synthesize_node)

# Define edges
graph_builder.add_edge(START, "initial_analyst")
graph_builder.add_edge("initial_analyst", "identify_weaknesses")

# After identifying weaknesses, either continue to next or synthesize
graph_builder.add_conditional_edges(
    "identify_weaknesses",
    route_after_identify,
    {
        "dequeue_next_weakness": "dequeue_next_weakness",
        "synthesize": "synthesize"
    }
)

# Dequeue → deep dive → reflect
graph_builder.add_edge("dequeue_next_weakness", "deep_dive")
graph_builder.add_edge("deep_dive", "reflect")

# After reflection, check the stack — continue drilling or move to synthesis
graph_builder.add_conditional_edges(
    "reflect",
    route_after_identify,
    {
        "dequeue_next_weakness": "dequeue_next_weakness",
        "synthesize": "synthesize"
    }
)

# Synthesis is the terminal node
graph_builder.add_edge("synthesize", END)

# Compile the graph
app = graph_builder.compile()


# ──────────────────────────────────────────────
# 10. Helper: Pretty-print the weakness tree
# ──────────────────────────────────────────────

def print_weakness_tree(all_weaknesses: Dict[str, WeaknessNode]):
    """Print a human-readable tree of all weaknesses."""
    if not all_weaknesses:
        print("  (No weaknesses identified)")
        return
    
    def print_node(node_id: str, indent: int = 0):
        node = all_weaknesses.get(node_id)
        if not node:
            return
        prefix = "  " * indent
        branch = "├─ " if indent > 0 else ""
        status = "✓" if node["explored"] else "○"
        print(f"{prefix}{branch}{status} {node['id']} | {node['topic']} | M:{node['materiality_score']} | depth {node['depth_level']}")
        for child_id in node["child_weaknesses"]:
            print_node(child_id, indent + 1)
    
    root_ids = sorted([wid for wid, node in all_weaknesses.items() if node["parent_id"] is None])
    for rid in root_ids:
        print_node(rid)


# ──────────────────────────────────────────────
# 11. Main Execution
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 72)
    print("  INVESTMENT ANALYSIS AGENT — Recursive Weakness Tree")
    print(f"  Model: Gemma4 (128K context) | Max depth: {MAX_DEPTH} | Threshold: {MATERIALITY_THRESHOLD}")
    print("=" * 72)
    
    company = input("\nEnter a company name or stock ticker to analyze (e.g., Apple, MSFT, Tesla): ").strip()
    if not company:
        company = "Alphabet (GOOGL)"
    
    print(f"\n{'─' * 72}")
    print(f"  Starting recursive analysis of: {company}")
    print(f"{'─' * 72}\n")
    
    initial_state: AgentState = {
        "company": company,
        "messages": [],
        "initial_analysis": None,
        "weakness_stack": [],
        "all_weaknesses": {},
        "finalized_weaknesses": [],
        "current_weakness_id": None,
        "final_synthesis": None,
        "depth_reached": False,
        "max_depth_hit_at": None,
    }
    
    node_visit_count = {
        "initial_analyst": 0,
        "identify_weaknesses": 0,
        "dequeue_next_weakness": 0,
        "deep_dive": 0,
        "reflect": 0,
        "synthesize": 0,
    }
    
    previous_state: AgentState = dict(initial_state)
    
    for event in app.stream(initial_state, stream_mode="values"):
        messages = event.get("messages", [])
        if not messages:
            continue
        
        last_msg = messages[-1]
        
        if event.get("initial_analysis") and node_visit_count["initial_analyst"] == 0:
            node_visit_count["initial_analyst"] += 1
            print(f"\n{'─' * 72}")
            print("  PHASE 1: INITIAL ANALYSIS COMPLETE")
            print(f"{'─' * 72}")
            print(last_msg.content[:2000] + ("\n... [truncated]" if len(last_msg.content) > 2000 else ""))
        
        current_wid = event.get("current_weakness_id")
        if current_wid and current_wid not in previous_state.get("finalized_weaknesses", []):
            wid = current_wid
            node = event.get("all_weaknesses", {}).get(wid, {})
            if node and not node.get("explored"):
                node_visit_count["dequeue_next_weakness"] += 1
                print(f"\n{'─' * 72}")
                print(f"  PHASE 3: DEEP DIVE #{node_visit_count['deep_dive'] + 1} — {node['topic']}")
                print(f"  ID: {wid} | Materiality: {node['materiality_score']}/5 | Depth: {node['depth_level']}/{MAX_DEPTH}")
                print(f"{'─' * 72}")
        
        for wid, node in event.get("all_weaknesses", {}).items():
            prev_explored = previous_state.get("all_weaknesses", {}).get(wid, {}).get("explored", False)
            if node.get("explored") and not prev_explored:
                node_visit_count["deep_dive"] += 1
                node_visit_count["reflect"] += 1
                print(f"  ✓ Deep dive complete: {node['topic']}")
                
                analysis = node.get("deep_analysis", "")
                if analysis:
                    print(f"\n  ANALYSIS ({len(analysis)} chars):")
                    print(f"  {analysis[:1500]}" + ("\n  ... [truncated]" if len(analysis) > 1500 else ""))
                
                print(f"\n  Current weakness tree:")
                print_weakness_tree(event.get("all_weaknesses", {}))
                
                stack = event.get("weakness_stack", [])
                if stack:
                    print(f"\n  Remaining in stack ({len(stack)}):")
                    for swid in stack:
                        snode = event.get("all_weaknesses", {}).get(swid, {})
                        if snode:
                            print(f"    - {swid}: {snode['topic']} (M:{snode['materiality_score']})")
                else:
                    print(f"\n  ✓ Weakness stack is empty — proceeding to synthesis.")
        
        previous_state = event
        
        if event.get("final_synthesis"):
            node_visit_count["synthesize"] += 1
            print(f"\n{'=' * 72}")
            print(f"  PHASE 5: FINAL SYNTHESIS")
            print(f"{'=' * 72}\n")
            
            synthesis = event["final_synthesis"]
            print(synthesis)
            
            print(f"\n{'─' * 72}")
            print(f"  ANALYSIS DEPTH REPORT")
            print(f"{'─' * 72}")
            print(f"  Maximum depth configured: {MAX_DEPTH}")
            print(f"  Maximum depth reached: {'Yes' if event.get('depth_reached') else 'No'}")
            if event.get("max_depth_hit_at"):
                print(f"  First truncation at: {event['max_depth_hit_at']}")
            print(f"  Total weaknesses identified: {len(event.get('all_weaknesses', {}))}")
            print(f"  Total deep dives completed: {node_visit_count['deep_dive']}")
            unexplored = sum(1 for n in event.get("all_weaknesses", {}).values() if not n["explored"])
            print(f"  Unexamined weaknesses (score < 3): {unexplored}")
            print(f"{'─' * 72}")
        
    print(f"\n{'=' * 72}")
    print(f"  ANALYSIS COMPLETE")
    print(f"{'=' * 72}")