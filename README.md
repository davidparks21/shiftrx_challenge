
# Scheduler Demo ShiftRx code challenge

Watch the demo of the application here:

[![Watch the video](https://img.youtube.com/vi/fzrDaVEj3Gc/0.jpg)](https://youtu.be/fzrDaVEj3Gc)

This application satisfies the coding challenge requirements. 
It's built with Flask (python backend), Bootstrap 5, Ollama with model `qwen2.5:7b-instruct-q4_K_M`.
This model runs on my local Nvidia 2080 (8GB) GPU. It's not perfect for the task, but it was the 
best of the 10ish models I tested. It performs all the tasks, though sometimes makes a few errors.
It stays on task, and self validates successfully, as shown in the demo. The project is built
in a docker container with a requirement that Ollama and the model serving is running on the
host.

Project Structure
```
src/
 ├─ app/                          # Flask UI + routing
 │   ├─ templates/                # Bootstrap 5 UI
 │   ├─ app.py                    # Entry point + HTTP handlers
 │   ├─ config.py                 # Configuration
 │   └─ __init__.py
 ├─ data_access_layer/            # SQLite access abstraction
 │   ├─ data_store.py
 │   └─ __init__.py
 ├─ data_object_model/            # Typed objects for schedules + conversation state
 │   ├─ application_state.py
 │   ├─ agent_communication.py
 │   └─ __init__.py
 └─ model_access_layer/           # LLM + tool interfaces
     ├─ agent.py                  # Agent interface
     ├─ agent_tools.py            # Tool calling implementations
     ├─ function_definitions.json # Tool definitions (passed to the model)
     └─ __init__.py

db/
 └─ app.sqlite3                # SQLLite DB files

docker/
 └─ Dockerfile                 # Dockerfile, image available at `davidparks21/shiftrx_challenge`
```

This organization separates UI, data storage, domain objects, and model-related 
logic—giving a foundation that can scale into a more complex agent system.

## Capabilities Demonstrated

| Requirement                             | Status | Notes                                                     |
| --------------------------------------- |---| --------------------------------------------------------- |
| Weekly schedule display                 | ✓ | Calendar grid for the current week, updates after changes |
| User input and conversation area        | ✓ | Chat-driven workflow                                      |
| Interaction with an LLM                 | ✓ | Local model via Ollama                                    |
| Extract intent + execute task           | ✓ | Tool calls based on model output                          |
| Stay on topic (schedule / organization) | ✓ | Constrained prompts and validation                        |
| Support call-off situations             | ✓ | Users can remove shifts via conversation                  |
| Database support                        | ✓ | SQLite backend                                            |
| Automated LLM evaluation                | ✓ | Validations embedded in agent workflow                    |

## Tooling supported by the prototype

- Set date range
- Add entries (requires approval confirmation)
- Delete entries (approval step)
- Answer questions based on visible schedule context

## LLM Workflow

The model acts as a structured agent with explicit function call routing:

1. User submits a message
2. LLM interprets intent using system prompt + examples
3. If a tool call is required:
   - Correct function is invoked (data layer validated)
   - UI updates the schedule database
4. Model then self-validates success or failure and reports back

Temperature and prompt strategy were tuned for reliability, given the smaller model.

> A higher-capacity model would reduce hallucination and improve date-range manipulation significantly.

## Implementation Approach

The development approach emphasized rapid UI functionality first, then integrated model capabilities gradually:

 - Built interactive scheduling UI with stubbed routes
 - Staged in LLM processing + function tools once workflow was stable
 - Iterated on prompts and model scaffolding to keep the agent aligned
 - Ensured clear abstraction layers:
    - Data Access Layer → SQLite CRUD
    - Model Access Layer → Agent + tool contracts
    - Data Object Model → Typed interaction structures
 - Some Bootstrap components (HTML layout) were bootstrapped using OpenAI Codex and clearly annotated in commits.

## De-scoped for POC (Future Work)

Extensions intentionally deferred to preserve delivery speed:

| Category         | Future Enhancements                          |
| ---------------- | -------------------------------------------- |
| Model reasoning  | Multi-step agent reasoning, parallel tools   |
| Evaluation       | Benchmark dataset + automated scoring loop   |
| Safety           | Approval workflows for sensitive operations  |
| Retrieval        | Notes/title RAG indexing                     |
| Test coverage    | Full unit + integration suite (normally TDD) |
| Function routing | Structured parsing for lower-tier models     |


These align with production-readiness goals: reliability, evaluation, routing accuracy, and auditability.


## Statement of AI use
I initially used this project to play with Codex. A few initial commits stood up the 
skeleton of the web app in flask and importantly the HTML using bootstrap 5 (I don't claim to be great 
at building beautiful UIs). These initial commits are contained in the git history and link
back to the original conversation. The rest of the project was built locally with AI tools 
doing no more than single function implementations. The logic and architecture design are all
my work.
