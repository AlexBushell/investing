"""
Unit tests for ivf_agent_recursive.py
Run with: python -m pytest test_ivf_agent.py -v
Or:        python test_ivf_agent.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from ivf.old.ivf_agent_recursive import (
    parse_materiality_score,
    parse_weakness_json,
    generate_weakness_id,
    build_tree_summary,
    build_analysis_archive,
    _extract_content,
    _prune_messages,
    MAX_DEPTH,
)
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage


# ─── Tests for parse_materiality_score ───────────────────────────────────

def assert_score(input_val, expected):
    result = parse_materiality_score(input_val)
    assert result == expected, f"parse_materiality_score({input_val!r}) = {result}, expected {expected}"


def test_materiality_score_integers():
    assert_score(5, 5)
    assert_score(3, 3)
    assert_score(1, 1)
    assert_score(0, 1)    # clamped
    assert_score(6, 5)    # clamped
    assert_score(-1, 1)   # clamped


def test_materiality_score_floats():
    assert_score(4.9, 4)  # truncated
    assert_score(3.0, 3)
    assert_score(1.2, 1)


def test_materiality_score_numeric_strings():
    assert_score("4", 4)
    assert_score("3/5", 3)
    assert_score("5/5", 5)
    assert_score("4.7", 4)
    assert_score("100", 5)  # clamped


def test_materiality_score_word_strings():
    assert_score("critical", 5)
    assert_score("high", 4)
    assert_score("major", 4)
    assert_score("notable", 3)
    assert_score("medium", 3)
    assert_score("minor", 2)
    assert_score("low", 2)
    assert_score("negligible", 1)


def test_materiality_score_case_insensitive():
    assert_score("HIGH", 4)
    assert_score("Critical", 5)
    assert_score("Notable", 3)


def test_materiality_score_edge_cases():
    assert_score("garbage", 3)  # default
    assert_score(None, 3)       # default
    assert_score("", 3)         # default


# ─── Tests for parse_weakness_json ───────────────────────────────────────

def test_parse_weakness_json_code_block():
    text = 'Some text\n```json\n{"weaknesses": [{"topic": "Risk A", "description": "Desc", "materiality_score": 4}]}\n```\nmore text'
    result = parse_weakness_json(text)
    assert result is not None
    assert len(result["weaknesses"]) == 1
    assert result["weaknesses"][0]["topic"] == "Risk A"
    assert result["weaknesses"][0]["materiality_score"] == 4


def test_parse_weakness_json_bare_json():
    text = '{"weaknesses": [{"topic": "Risk B", "description": "Desc B", "materiality_score": 3}]}'
    result = parse_weakness_json(text)
    assert result is not None
    assert len(result["weaknesses"]) == 1
    assert result["weaknesses"][0]["topic"] == "Risk B"


def test_parse_weakness_json_empty():
    text = '{"weaknesses": []}'
    result = parse_weakness_json(text)
    assert result is not None
    assert result["weaknesses"] == []


def test_parse_weakness_json_invalid():
    assert parse_weakness_json("") is None
    assert parse_weakness_json("not json") is None
    assert parse_weakness_json("{}") is None  # no "weaknesses" key
    assert parse_weakness_json('{"x": 1}') is None  # no "weaknesses" key


def test_parse_weakness_json_malformed_items():
    """Null and non-dict items in the list should be skipped."""
    text = '{"weaknesses": [null, "string", {"topic": "OK", "description": "Good", "materiality_score": 3}]}'
    result = parse_weakness_json(text)
    assert result is not None
    assert len(result["weaknesses"]) == 1
    assert result["weaknesses"][0]["topic"] == "OK"


def test_parse_weakness_json_word_scores():
    text = '{"weaknesses": [{"topic": "X", "description": "Y", "materiality_score": "High"}]}'
    result = parse_weakness_json(text)
    assert result is not None
    assert result["weaknesses"][0]["materiality_score"] == 4


# ─── Tests for generate_weakness_id ──────────────────────────────────────

def test_generate_root_id():
    assert generate_weakness_id(None, set()) == "W1"
    assert generate_weakness_id(None, {"W1", "W2"}) == "W3"
    assert generate_weakness_id(None, {"W5", "W10"}) == "W11"


def test_generate_child_id():
    assert generate_weakness_id("W1", set()) == "W1-1"
    assert generate_weakness_id("W1", {"W1-1"}) == "W1-2"
    assert generate_weakness_id("W1", {"W1-1", "W1-2", "W1-3"}) == "W1-4"


def test_generate_nested_id():
    assert generate_weakness_id("W1-2", set()) == "W1-2-1"
    assert generate_weakness_id("W1-2", {"W1-2-1"}) == "W1-2-2"


# ─── Tests for _extract_content ──────────────────────────────────────────

class FakeResponse:
    def __init__(self, content=None, text=None):
        self.content = content
        self.text = text


def test_extract_content():
    assert _extract_content(FakeResponse(content="Hello")) == "Hello"
    assert _extract_content(FakeResponse(text="World")) == "World"
    assert _extract_content(FakeResponse(content="")) == ""
    assert _extract_content("raw string") == "raw string"


# ─── Tests for _prune_messages ───────────────────────────────────────────

def test_prune_messages_under_limit():
    msgs = [SystemMessage(content="sys"), HumanMessage(content="hi")]
    pruned = _prune_messages(msgs, max_recent=10)
    assert pruned == msgs


def test_prune_messages_over_limit():
    msgs = [SystemMessage(content="sys")] + [HumanMessage(content=str(i)) for i in range(20)]
    pruned = _prune_messages(msgs, max_recent=5)
    # Expect: system prompt + 4 recent messages
    assert len(pruned) == 5, f"Expected 5, got {len(pruned)}"
    assert isinstance(pruned[0], SystemMessage), "First must be system"
    assert pruned[-1].content == "19", "Last should be most recent"


def test_prune_messages_no_system():
    """Should work even without a system message."""
    msgs = [HumanMessage(content=str(i)) for i in range(20)]
    pruned = _prune_messages(msgs, max_recent=5)
    assert len(pruned) <= 5
    assert pruned[-1].content == "19"


# ─── Tests for build_tree_summary / build_analysis_archive ───────────────

def test_tree_summary_empty():
    assert build_tree_summary({}) == "(No weaknesses identified yet.)"


def test_analysis_archive_empty():
    assert build_analysis_archive([], {}) == "(No deep analyses completed yet.)"


# ─── Run all tests if executed directly ─────────────────────────────────

if __name__ == "__main__":
    # Collect and run all test_* functions
    import inspect
    this_module = sys.modules[__name__]
    tests = [fn for name, fn in inspect.getmembers(this_module) if name.startswith("test_")]
    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  ✓ {test_fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {test_fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {test_fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    
    print(f"\n{'=' * 40}")
    print(f"  {passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)