# Querying Knowledge Bases from Your SMA

How to populate, organize, and query org-specific knowledge bases using the `search_knowledge` mesh tool.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [How Data Gets Into the Knowledge Base](#how-data-gets-into-the-knowledge-base)
4. [Datasets & Node Sets](#datasets--node-sets)
5. [The search_knowledge Mesh Tool](#the-search_knowledge-mesh-tool)
6. [Search Types Explained](#search-types-explained)
7. [Code Examples](#code-examples)
8. [How It Works Under the Hood](#how-it-works-under-the-hood)
9. [Result Format](#result-format)
10. [Troubleshooting](#troubleshooting)

---

## Overview

TAP provides each org with an isolated knowledge base powered by [Cognee](https://github.com/topoteretes/cognee). Orgs can store and query structured knowledge — policy documents, domain expertise, training data, user memory, and custom datasets.

Your SMA queries this knowledge through the `search_knowledge` mesh tool. Like all mesh tools, it returns an intent payload that Gateway executes on your behalf, handling authentication and org isolation automatically.

---

## Prerequisites

- Your org must be provisioned in TAP (knowledge base provisioning happens automatically on signup)
- Data must be ingested into at least one dataset before you can search it

---

## How Data Gets Into the Knowledge Base

Data enters the knowledge base through two paths:

### 1. File Upload (TAP UI)

Users upload PDFs, documents, and text files through the TAP frontend's Knowledge Base section.

- Uploaded files are stored in a dataset named `org_{org_id}_context`
- An optional `node_set` tag can be passed for sub-grouping
- After upload, the platform automatically builds a knowledge graph from the raw content — this is what makes the data searchable

### 2. Platform APIs

TAP platform services can write text data programmatically (e.g., SMA preferences, user memory, social profiles, session summaries).

- Dataset name and node_set are defined by the calling service
- Data must be processed into a knowledge graph after ingestion before it becomes searchable

---

## Datasets & Node Sets

The knowledge base uses a two-level data organization system:

### Datasets

Named containers that scope permissions and data processing.

| Dataset | Used For | Created By |
|---------|----------|------------|
| `ltm` | User memory, SMA preferences, social profiles | Platform (default) |
| `org_{org_id}_context` | File uploads (PDFs, docs) | TAP UI file upload |
| Custom (e.g., `org_policies`) | Developer-defined knowledge domains | Your ingestion pipeline |

### Node Sets

Tags within a dataset for sub-grouping. Set on write, filtered on read.

| Node Set Pattern | Purpose |
|------------------|---------|
| `user_{user_id}` | Per-user data (memory, preferences) |
| `org_training` | Org-wide SMA training data and preferences |
| `social_{user_id}` | User social intelligence profiles |
| `sessions` | Session summaries and history |
| Custom tags | Your own logical partitions (e.g., `policy_docs`, `product_faq`) |

**How they interact:**
- **Write**: `node_set=["policy_docs"]` tags data when ingested
- **Read**: `node_set=["policy_docs"]` filters results to only matching nodes
- **Omit node_set on read**: Returns results from all nodes in the dataset

---

## The search_knowledge Mesh Tool

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | *required* | Natural language search query |
| `dataset_name` | `str` | `"ltm"` | Which dataset to search |
| `node_set` | `List[str]` or `None` | `None` | Filter by node tags (omit to search all nodes) |
| `search_type` | `str` | `"GRAPH_COMPLETION"` | Search algorithm (see [Search Types](#search-types-explained)) |
| `limit` | `int` | `10` | Max results (clamped to 1-50) |

### Import

```python
from tap_core.tools import search_knowledge
```

The tool is auto-injected into your agent by `tap_wrapper` — no manual registration needed.

---

## Search Types Explained

| Type | LLM-Powered? | Best For | Node Set Filtering? |
|------|:------------:|----------|:-------------------:|
| `GRAPH_COMPLETION` | Yes | Relationship queries, connecting dots across documents | Respected |
| `CHUNKS` | No | Fast vector lookups, raw document passages | **Ignored** |
| `RAG_COMPLETION` | Yes | Q&A with source attribution | Respected |
| `INSIGHTS` | Yes | Structured fact extraction | Respected |
| `SUMMARIES` | Yes | Overview/digest of matching content | Respected |

### Choosing a Search Type

- **`GRAPH_COMPLETION`** (default): Best for most queries. Traverses the knowledge graph to find relationships between concepts. Use when asking questions that require connecting information across multiple documents.

- **`CHUNKS`**: Fastest option. Returns raw text passages via vector similarity. Use when you need exact document excerpts or don't need LLM synthesis. **Warning: CHUNKS ignores `node_set` — all results from the dataset are returned regardless of node filtering.**

- **`RAG_COMPLETION`**: Best for authoritative Q&A. Retrieves relevant chunks and generates a synthesized answer with source attribution. Use when you need a definitive answer grounded in the documents.

- **`INSIGHTS`**: Extracts structured facts and relationships. Use when you need specific data points rather than narrative answers.

- **`SUMMARIES`**: Generates a condensed overview of matching content. Use when you need a high-level picture rather than specific details.

---

## Code Examples

### Basic: Query the Default LTM Dataset

```python
intent = search_knowledge(
    query="What are this user's communication preferences?",
)
# Searches the "ltm" dataset with GRAPH_COMPLETION, returns up to 10 results
```

### Custom Dataset with Node Set

```python
intent = search_knowledge(
    query="What is our refund policy for enterprise customers?",
    dataset_name="org_policies",
    node_set=["policy_docs"],
    search_type="RAG_COMPLETION",
    limit=5,
)
```

### Multiple Search Types for Different Needs

```python
# Get relationship-aware answer
graph_intent = search_knowledge(
    query="How does our onboarding process connect to compliance requirements?",
    dataset_name="org_policies",
    search_type="GRAPH_COMPLETION",
)

# Get raw document passages for citation
chunks_intent = search_knowledge(
    query="onboarding compliance requirements",
    dataset_name="org_policies",
    search_type="CHUNKS",
    limit=3,
)
```

### In Agent Prompt Instructions

Tell your LLM when and how to use the tool in your `agent/prompts.py`:

```python
AGENT_INSTRUCTIONS = """
When the user asks about company policies or procedures:
1. Use search_knowledge with dataset_name="org_policies" and search_type="RAG_COMPLETION"
   to find authoritative answers
2. If the answer needs context from multiple documents, use search_type="GRAPH_COMPLETION"
3. Always cite which policy the answer came from

When the user asks about their past interactions:
1. Use search_knowledge with the default dataset ("ltm") and
   node_set=["user_{user_id}"] to scope to their personal data
2. Use search_type="SUMMARIES" for overview questions

If search_knowledge returns empty results, let the user know that the relevant
knowledge hasn't been uploaded yet and suggest they upload documents via the
Knowledge Base section in settings.
"""
```

---

## How It Works Under the Hood

```
Your SMA calls search_knowledge(query, dataset_name, ...)
    │
    ▼
tap_core returns JSON intent payload (no network call from your SMA)
    │
    ▼
Gateway intercepts the intent and authenticates on behalf of your org
    │
    ▼
Gateway queries the knowledge base, scoped to your org's tenant
    │
    ▼
Results are normalized and returned to your agent as tool output
```

**Org isolation**: All queries are scoped to your org's tenant via JWT authentication. Your SMA cannot access another org's data.

**No direct access needed**: Your SMA never talks to the knowledge base directly. Gateway handles authentication, request forwarding, and result normalization. You don't need any credentials or network configuration in your Cloud Run container.

---

## Result Format

Each search result contains:

```json
{
    "content": "The matched text or synthesized answer",
    "score": 0.87,
    "data_id": "abc123-def456",
    "metadata": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `content` | `str` | The matched text, knowledge graph traversal result, or synthesized answer (depends on search type) |
| `score` | `float` | Relevance score (0.0 - 1.0, higher is better) |
| `data_id` | `str` or `null` | Identifier for the source data item. For CHUNKS, this is the parent document ID. |
| `metadata` | `dict` or `null` | Any metadata attached to the item during ingestion |

Results are returned as a list, ordered by descending relevance score.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Empty results | Dataset name mismatch | Verify `dataset_name` matches what was used during ingestion. File uploads use `org_{org_id}_context`. |
| Empty results | Data not yet processed | Data must be processed into a knowledge graph after ingestion. This happens automatically for UI uploads but may take a few minutes. |
| Empty results | Node set mismatch | Verify `node_set` on read matches the tags used on write (exact string match). |
| CHUNKS returns unscoped results | Expected behavior | CHUNKS ignores `node_set` filtering — this is by design. Use GRAPH_COMPLETION if you need node scoping. |
| Dataset doesn't exist | No data ingested | Data must be ingested first via TAP UI file upload or platform APIs before the dataset exists. |
| Slow responses | LLM-powered search type | GRAPH_COMPLETION, RAG_COMPLETION, INSIGHTS, and SUMMARIES use LLM calls. Use CHUNKS for fastest results. |
| Results from wrong org | Should not happen | Gateway enforces org isolation via JWT. If you suspect cross-org leakage, report it immediately. |
