# **The Architectures of Autonomy**

RAG-Optimized Pattern Library for AI Agent Architects

# **Module 1: Foundational Cognitive Patterns**

## **Pattern: Chain of Thought (CoT) & Chain of Verification**

**Metadata:**

* **Tags:** Reasoning, Logic, Math, Verification  
* **Constraint Solved:** Ambiguity, Complex Logic, Hallucination  
* **Frameworks:** Google ADK (BuiltInPlanner), General  
* **Hypothetical Queries:** 'How do I make the agent think before acting?', 'How to reduce hallucinations in complex tasks?'

### **Definition**

Chain of Thought (CoT) serves as the baseline cognitive pattern for complex reasoning. It induces the model to generate intermediate reasoning steps ('thoughts') before committing to a final answer.

### **Mechanism**

1. Thinking Budget: The model is allocated a specific token limit to perform internal reasoning.  
2. Verification (CoV): The agent generates a baseline response, drafts verification questions to test the premises, answers them independently, and synthesizes a final verified answer.

### **Framework Implementation**

* **Google ADK:** Uses the BuiltInPlanner with a ThinkingConfig object. Developers set a thinking\_budget (e.g., 2048 tokens), allowing the model to decompose instructions without HTTP latency.  
* **General:** Implemented via prompt engineering or 'scratchpad' tokens.

## **Pattern: ReAct (Reason and Act)**

**Metadata:**

* **Tags:** Tool Use, API Interaction, Search, Standard Loop  
* **Constraint Solved:** Knowledge Cutoff, Need for Real-time Data  
* **Risk:** High Latency, Reasoning Drift, Infinite Loops  
* **Hypothetical Queries:** 'How does an agent use tools?', 'What is the standard loop for agents?', 'Why is my agent stuck in a loop?'

### **Definition**

The ReAct pattern represents the standard operating procedure for autonomous agents, interleaving reasoning traces with actionable tool execution.

### **Mechanism**

1. Thought: Analyze goal and current state.  
2. Action: Select tool and define parameters.  
3. Observation: Execute tool and read output.  
4. Synthesis: Repeat cycle until goal is met.

### **Framework Implementation**

* **LangGraph:** Models ReAct as a cyclic state graph with a 'Reasoning Node' and 'Tools Node.' Allows for 'Time Travel' debugging.  
* **Google ADK:** Default behavior of LlmAgent. Can be wrapped in LoopAgent to enforce iteration limits.

### **Trade-offs**

* **Pros:** Flexible, handles dynamic environments well.  
* **Cons:** High token cost (history buildup) and latency. Prone to 'Reasoning Drift' in long sessions.

## **Pattern: Plan-and-Solve (Plan-and-Execute)**

**Metadata:**

* **Tags:** Planning, Long-horizon tasks, Multi-step  
* **Constraint Solved:** Myopia (Short-sightedness), Reasoning Drift, Dependency Management  
* **Hypothetical Queries:** 'How to handle complex coding tasks?', 'My agent forgets the plan halfway through.'

### **Definition**

Separates high-level strategy from low-level execution to prevent the model from getting lost in details.

### **Mechanism**

1. Planner: A strong model (e.g., Gemini 1.5 Pro) generates a Directed Acyclic Graph (DAG) of sub-tasks.  
2. Executor: Worker agents execute each task.  
3. Replanner: Periodically re-evaluates the plan against the current state.

### **Framework Implementation**

* **CrewAI:** Process.hierarchical uses a Manager Agent to plan and delegate.  
* **LangGraph:** Explicit 'plan' object in the state. Cycles between 'execute\_step' and 'replan' nodes.

# **Module 2: Orchestration & Scaling Patterns**

## **Pattern: Map-Reduce**

**Metadata:**

* **Tags:** Big Data, Summarization, Document Processing, Parallelism  
* **Constraint Solved:** Context Window Bottleneck, Token Limits  
* **Hypothetical Queries:** 'How to summarize 100 documents?', 'The file is too large for the context window.'

### **Definition**

Adapted from distributed computing, Map-Reduce breaks datasets into independent chunks for parallel processing.

### **Mechanism**

1. Map (Fan-out): Segment data (e.g., 500 pages) into chunks. Spawn 'Mapper' agents for each chunk to extract specific data.  
2. Reduce (Fan-in): A 'Synthesizer' agent aggregates partial results into a final output.

### **Framework Implementation**

* **Google ADK:** Use ParallelAgent to run Mappers. Use SequentialAgent to pipe results to a Summarizer. Uses session state keys to manage data.  
* **CrewAI:** Set async\_execution=True for tasks. Final task acts as the reducer.

## **Pattern: Parallel Fan-Out (The 'Octopus')**

**Metadata:**

* **Tags:** Real-time, Multi-perspective, Speed  
* **Constraint Solved:** Latency, Stale Data  
* **Hypothetical Queries:** 'How to check multiple sources at once?', 'How to speed up research?'

### **Definition**

Splits the perspective or domain rather than the data. A central dispatcher spawns specialized agents to address different aspects of a problem simultaneously.

### **Mechanism**

A 'Router' agent spawns multiple specialists (e.g., Security Scanner, Style Checker) to run on the same artifact simultaneously. Results are joined at a synchronization node.

### **Framework Implementation**

* **LangGraph:** Use Send API or fan-out edges.  
* **Google ADK:** ParallelAgent with distinct specialized sub-agents.

# **Module 3: Quality Assurance Patterns**

## **Pattern: Reflection & Self-Correction**

**Metadata:**

* **Tags:** Quality Control, Coding, Debugging, Reliability  
* **Constraint Solved:** Hallucinations, Syntax Errors, Logic Bugs  
* **Hypothetical Queries:** 'How to fix code automatically?', 'How to improve accuracy without a human?'

### **Definition**

Creates a feedback loop where the agent critiques its own work.

### **Mechanism**

1. Generate: Produce artifact (e.g., code).  
2. Critique: Prompt model (or Critic agent) to evaluate against constraints.  
3. Refine: Inject feedback and regenerate.

### **Framework Implementation**

* **Google ADK:** LoopAgent wrapping \[Generator, Critic\]. Also uses 'Reflect and Retry' plugin for tool failures.  
* **LangGraph:** Cyclic graph where stderr (error output) is routed back to the generation node.

# **Module 4: Framework Selection Guide**

## **Comparison: Google ADK vs. LangGraph vs. CrewAI**

**Metadata:**

* **Tags:** Tool Selection, Architecture Choice, Tech Stack

| Feature | Google ADK | LangGraph | CrewAI |
| :---- | :---- | :---- | :---- |
| **Best For** | Enterprise Production, Google Cloud Native | Complex Logic, State Control, Debugging | Rapid Prototyping, Role-Playing |
| **Philosophy** | "Software Engineering" (Typed, Compiled) | "State Machines" (Cyclic Graphs) | "Team Management" (Role-based) |
| **State Mgmt** | Session Services (Vertex AI) | Shared Schema / Checkpointers | Unstructured / Pydantic |
| **Parallelism** | ParallelAgent (Managed Threads) | Send API / Fan-out Nodes | Async Tasks |
| **Infrastructure** | Serverless (Vertex Agent Engine) | Self-Hosted / LangGraph Cloud | Self-Hosted |

### **Recommendation Logic**

* Choose Google ADK if: You need strict security (HIPAA/SOC2), multimodal interaction (Audio/Video), or distributed 'Agent-to-Agent' mesh architecture.  
* Choose LangGraph if: You need 'Time Travel' debugging, complex human-in-the-loop flows, or fine-grained control over memory.  
* Choose CrewAI if: You need to stand up a demo in minutes or map a problem to a human organizational chart.