# ForgeIQ — Intelligent Manufacturing Scheduling

ForgeIQ is a manual-entry manufacturing scheduling workbench for general production and automotive machining/inspection workflows such as engine blocks, crankshafts and brake discs. It runs documented dispatch heuristics and bounded state-space search against entered constraints, stores versioned schedule snapshots, renders actual operations in a Gantt chart, compares measured metrics and transparently recommends the best feasible selected algorithm for the chosen objective. The recommender is deterministic; it is not a trained AI model.

## Features

- Empty first launch; no automatic sample data, fake KPIs or fabricated schedules. Use **Load Sample Dataset** or **Load automotive demo** only when you choose to; each is deterministic, marked **SAMPLE**, and removable.
- Full job, machine and ordered-operation entry, editing, viewing and deletion. Search and priority filters are available for jobs.
- Single-operation/parallel-machine and job-shop scheduling, plus a separately labelled permutation-flow-shop scenario for the NEH heuristic.
- FCFS, SPT, EDD, Priority-Based and LPT precedence-aware dispatch rules; NEH only for supported permutation flow shops. A*, Uniform Cost, Greedy Best-First, Breadth-First and Depth-First bounded state-space search are separately labelled. Search limits, state counts, termination and optimality evidence are persisted; no unsupported global-optimality claim.
- Constraint validation, machine availability and maintenance windows, processing capabilities, setup time, job precedence and machine-capacity protection; infeasibility is explained rather than drawn as a valid schedule.
- Actual-output machine-row Gantt with filters, zoom, algorithm switching, tooltips and task details; comparison table, objective chart, measured recommendation and explanations.
- Saved/retrievable run snapshots, selected-algorithm save, CSV exports and printer-friendly report.
- FastAPI REST API and interactive API docs at `/docs`.
- A separate operator-triggered **Dynamic Rescheduling** workflow that applies breakdown, maintenance, delay, urgent-order or reported machine-risk events to a saved run; supports feasible dispatch or search methods and compares the immutable original plan with a fully validated revision.
- Automotive predicate facts, executable planning actions and a compact AI-syllabus mapping; choose **English** or **தமிழ்** from the sidebar language toggle (the preference persists in this browser).
- Responsive layouts for compact phones (320px and wider), phones, tablets and desktop, with touch-sized controls and independently scrollable navigation, tables and Gantt timelines.

## Project layout

```text
forgeiq/
├── alembic.ini / backend/migrations/ # versioned, additive persistent schema
├── app.config.ts                    # ForgeIQ project logo metadata
├── backend/
│   ├── app/                 # FastAPI, SQLAlchemy models, API and scheduling engine
│   │   ├── api/routes.py
│   │   ├── scheduling/      # dispatch, A*/UCS/Greedy/BFS/DFS, knowledge, planning, automotive workflows and rescheduling
│   │   ├── database.py
│   │   ├── models.py
│   │   └── schemas.py
│   ├── migrations/          # versioned Alembic schema revisions
│   ├── tests/               # isolated SQLite, migration and API tests
│   └── requirements.txt
├── frontend/src/            # React/TypeScript workspace, automotive CRUD, scheduling, rescheduling, results and knowledge/planning pages; bilingual UI, Gantt, API client and responsive styling
├── frontend/tests/          # Vitest/Testing Library interactions
├── public/manus-routes.json
├── Dockerfile
├── package.json / pnpm-lock.yaml
├── .env.example
└── README.md
```

## Requirements

- Python 3.11 or newer (validated with the included Python 3.12-compatible requirements).
- Node.js 22 LTS and Corepack/pnpm 11.25.0 (the version is pinned in `package.json`).
- Windows 11, macOS or Linux for local development.

## Local setup — Windows 11 CMD

Open a first Command Prompt in the repository root:

```bat
cd C:\path\to\forgeiq
corepack pnpm install
copy .env.example .env
```

Create and activate the Python environment, install dependencies, and apply the recorded local SQLite schema migration:

```bat
cd backend
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m app.init_db
```

Start the API (leave this terminal running):

```bat
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open a second Command Prompt in the repository root to run Vite:

```bat
cd C:\path\to\forgeiq
corepack pnpm dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:5173`). API calls use the relative `/api/v1` path; `vite.config.ts` proxies them to FastAPI. The default `.env.example` leaves `VITE_API_URL` blank for that proxy. The interactive API documentation is at `http://127.0.0.1:8000/docs`.

### Windows PowerShell equivalent

```powershell
Set-Location C:\path\to\forgeiq
corepack pnpm install
Copy-Item .env.example .env
Set-Location backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m app.init_db
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second PowerShell terminal, from the repository root:

```powershell
Set-Location C:\path\to\forgeiq
corepack pnpm dev
```

If PowerShell blocks virtual-environment activation, use CMD commands instead or run the Python executable by its full path; do not loosen machine-wide execution policy just for ForgeIQ.

### macOS and Linux

In terminal one, from the project root:

```sh
cd /path/to/forgeiq
corepack pnpm install
cp .env.example .env
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m app.init_db
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In terminal two, from the project root, run `corepack pnpm dev` and open the Vite URL (normally port 5173). Keep the API terminal running; `/docs` is served on port 8000.

## Build and serve the compiled frontend from FastAPI

Vite development mode is convenient for editing; the same FastAPI app can also serve the compiled React build and `/api/v1` on one origin:

```bat
cd C:\path\to\forgeiq
corepack pnpm build
cd backend
.venv\Scripts\activate.bat
uvicorn app.main:app --host 0.0.0.0 --port 3000
```

Open `http://127.0.0.1:3000`. `http://127.0.0.1:3000/docs` remains available. If `frontend/dist` has not been built, FastAPI returns a setup message at `/` rather than a fake page.

## Configuration

Copy `.env.example` to `.env` and set only the values relevant to your environment. `VITE_API_URL` is the frontend API base, e.g. `https://forgeiq-api.example.com`; keep it blank for same-origin or Vite-proxied development. `VITE_API_PROXY_TARGET` changes the Vite development proxy (default `http://127.0.0.1:8000`). `CORS_ORIGINS` is a comma-separated list of exact origins. Keep `DATABASE_URL` empty to use a local SQLite file at `backend/data/forgeiq.db`, or set it to your selected MySQL-compatible or PostgreSQL connection string. External database connections require TLS: MySQL uses a certificate- and hostname-verified Python SSL context; PostgreSQL URLs are forced to `sslmode=verify-full`. For PostgreSQL providers with a private CA, configure `sslrootcert` to point to that trusted CA file; verification errors fail closed. Plaintext MySQL and PostgreSQL connections are never permitted. The additive Alembic migration is applied only when its revision is pending and records progress in `alembic_version`. Never commit `.env`, credentials or database dumps.

In the managed ForgeIQ preview, the platform's persistent database is selected through `DATABASE_URL`; it is separate from the local SQLite default. Preview development and its managed database may share state with a published service, so do not use sample data as a production seed. TLS verification is enforced for every external MySQL or PostgreSQL database URL.

Automotive component/status, machine capability/maintenance and operation capability columns are introduced by additive Alembic revision `0003_automotive_ai_search`. Existing generic rows receive safe defaults; the migration neither replaces the database nor deletes user records. `python -m app.init_db` applies pending recorded revisions to the local database.

## Scheduling behavior and metric definitions

- Times are normalized to UTC internally and the schedule horizon origin is the earliest entered job release time. Result operation times are minutes from that origin and include display-ready UTC timestamps.
- Operation occupancy includes its processing time, operation setup and the machine's configured setup time. Operations are non-preemptive. Job-shop dispatch rules make decisions only among precedence-ready operations and assigned machines; deterministic ties use release time, due time, priority, sequence and stable IDs as appropriate.
- FCFS orders eligible jobs by release/queue arrival. SPT/LPT use operation processing + setup duration. EDD uses the earliest job due time. Priority ranks Critical, High, Medium, Low, then uses release and due times. These rules are dispatching heuristics, not proofs of a global optimum.
- NEH is supported only when every job shares the same ordered sequence of distinct single-machine stages. The interface exposes it only in the explicitly named permutation-flow-shop mode.
- Makespan is final operation completion minus horizon origin. Total completion time sums each job's completion offset from the origin. Tardiness is `max(0, completion - due)`; maximum lateness retains negative (early) values; tardy count counts jobs whose completion exceeds due time.
- Average waiting is the average interval from job release/predecessor completion until an operation starts; it excludes machine idle time. Machine utilization is operation processing minutes divided by available machine minutes between the horizon origin and final completion; unavailable machine time and setup are excluded from the processing numerator. Computation time is actual backend elapsed time per algorithm.
- A machine is configured with one available-from / optional available-until window; the **baseline** scheduler does not simulate multiple shift calendars. The Dynamic Rescheduling workflow adds event-specific, operator-entered breakdown and maintenance windows to a saved-run branch. These are simulations, not live sensor monitoring. The due-date switch may make any run with a tardy job infeasible; otherwise due dates are evaluation criteria.
- Recommendations reject infeasible results, sort by the chosen objective (utilization higher is better; other objectives lower is better), then configured secondary objectives, then a stable alphabetical algorithm-name tie-break. A schedule's `dataset_version` and saved input snapshot make old results reproducible; changes in jobs/machines/operations flag those runs as outdated.

## AI search, knowledge, planning and syllabus mapping

The search methods are real bounded algorithms over the same validated manufacturing states and applicable actions, not score labels or precomputed schedules. A state records scheduled/completed operations, machine free times, job progress and accumulated cost. An action assigns one ready operation to an eligible, capability-compatible machine at a feasible time, updating its completion, machine occupancy and job progress. A goal requires a complete feasible schedule; an unsuccessful or interrupted search never returns a partial Gantt.

- `A*` orders by `f(n) = g(n) + h(n)`: `g(n)` is a non-negative configurable weighted scheduling cost using makespan, total tardiness, avoidable idle/gap time, setup and reported machine-risk terms; each enabled weight is explicit in the request/result snapshot. `h(n)` is the documented admissible remaining-work lower bound for the supported cost model. A* reports optimality only when that model's complete search proves it; a goal found at a limit is usable but is marked feasible/unproven.
- **Uniform Cost Search (UCS)** orders by accumulated `g(n)`; **Greedy Best-First** orders by `h(n)`; **Breadth-First** and **Depth-First** use their respective frontier order. They share validation, actions, duplicate-state handling and configured bounds, but are not assigned A*'s optimality guarantee. FCFS/SPT/EDD/Priority-Based/LPT remain distinct dispatch heuristics; NEH remains limited to the explicit permutation-flow-shop scenario.
- Expansion and time budgets are configurable (UI defaults: 2,500 states and 2 seconds; UI ceilings: 100,000 expansions and 30 seconds). Search results include actual expanded, generated and duplicate counts, actual measured runtime, stop/termination status, the configured limits, and whether optimality was proved for the search-cost model. Recommendations independently rank feasible returned schedules by the selected primary objective and deterministic tie-breakers; an A* proof about weighted search cost is not a claim that every displayed metric is globally optimal.
- `/api/v1/knowledge-base` derives `Compatible(operation,machine)`, `Precedes(operation_A,operation_B)`, `Available(machine,time)` and `Finished(operation,time)` facts from entered records/calendars and the current feasible saved schedule. `/api/v1/planning/model` returns applicable operation-assignment actions with explicit preconditions and effects; these are the actions consumed by search, not disconnected teaching examples. Validation also rejects duplicates, incompatible/unavailable assignments, machine overlap, broken precedence and incomplete schedules.
- **Course mapping:** A* = `f=g+h`; UCS = `g`; Greedy Best-First = `h`; BFS/DFS = queue/stack frontier order; structured domain facts = knowledge representation; the precondition/effect action = classical planning. The in-app Knowledge & Planning view exposes live facts, currently applicable actions, configurable educational automotive route templates and the mapping. The automotive sample is loaded only on explicit user action, is visibly labelled simulated, and is removable.

## Dynamic rescheduling

Open **Dynamic Rescheduling** after generating a feasible Job Shop or Single-Operation / Parallel-Machine schedule. Choose a saved run, a feasible existing dispatch or state-space search algorithm, the event time and a disruption. Search rescheduling uses explicit expansion/time limits and non-negative cost weights; the new run saves its own measured search status and statistics. The operator starts each simulation explicitly; ForgeIQ does not listen to factory sensors or run an unattended monitor. NEH's permutation-flow-shop mode is not supported by dynamic rescheduling and is rejected with an explanation.

Supported events are machine breakdown (block a selected machine through its repair time), maintenance (block it for the entered window), processing delay (extend an operation that is active at the event time and honor its downstream precedence), urgent order (add a Critical-priority job released at the event time, with a due time and one or more sequenced operations restricted to eligible existing machines), and operator-reported high machine risk. Risk reporting is a manual input—not a prediction; a safe eligible machine is preferred, and any necessary risky fallback is disclosed. An urgent order enters the editable manufacturing dataset and increments its version only if the revised schedule is feasible. The source run remains unchanged; the new run saves its input/event snapshot.

Completed operations at the event time remain fixed. Unaffected operations already in progress remain non-preemptive and fixed. A failed/maintained machine's interrupted in-progress operation is conservatively treated as a restart-from-zero at its full processing duration after repair; the result explains this assumption. Pending work is re-dispatched under the same release, operation precedence, machine-capacity, availability and eligible-machine constraints. Infeasible events do not persist an event, partial urgent order or invalid Gantt. The result shows the event explanation, impacted and moved work, the original and revised Gantts, before/after makespan, tardiness, utilization, idle and setup metrics, and schedule stability. Stability is the percentage of operations shared by both schedules whose assigned machine, start and end remain unchanged.

## REST API

All routes are under `/api/v1` and return JSON. FastAPI's generated reference is `/docs`.

| Method | Route | Purpose |
| --- | --- | --- |
| GET, POST | `/jobs` | List or create jobs |
| GET, PUT, DELETE | `/jobs/{job_id}` | Read, edit or remove a job |
| GET, POST | `/machines` | List or create machines |
| PUT, DELETE | `/machines/{machine_id}` | Edit or remove a machine; used machines cannot be deleted |
| GET, POST | `/operations` | List or create operations |
| PUT, DELETE | `/operations/{operation_id}` | Edit or remove an operation |
| GET | `/dataset-version` | Read the manufacturing dataset version used to identify stale runs |
| GET | `/automotive/workflows` | Read the editable engine-block, crankshaft and brake-disc learning routes |
| POST | `/automotive/sample` | Explicitly load the removable, labelled automotive learning dataset into an empty workspace |
| GET | `/knowledge-base` | Read persisted predicate facts grounded in current entered and scheduled records |
| GET | `/planning/model` | Read planning validity, rules and currently applicable operation actions with preconditions/effects |
| POST | `/schedules/generate` | Validate input, run algorithms, persist results and recommendation |
| GET | `/schedules` | List saved runs (stale state is included) |
| GET | `/schedules/{schedule_id}` | Retrieve a run and input snapshot |
| GET | `/schedules/{schedule_id}/comparison` | Read calculated comparison metrics |
| GET | `/schedules/{schedule_id}/gantt?algorithm_name=SPT` | Read actual scheduled operations |
| GET | `/schedules/{schedule_id}/recommendation` | Read the deterministic recommendation and ranking |
| POST | `/schedules/{schedule_id}/select` | Save a feasible algorithm result as the selected schedule |
| POST | `/schedules/{schedule_id}/reschedule` | Apply one validated production event and persist a feasible revised run plus immutable before/after history |
| GET | `/schedules/{schedule_id}/reschedules` | Read the event history attached to the selected schedule and its run lineage |
| GET | `/health` | Lightweight API status |
| GET | `/api/health` | Database-aware readiness check for containers |
| GET, DELETE | `/sample` | Explicitly load or remove only labelled deterministic sample records |

Job, machine and operation IDs are unique and stable (ID changes require delete/recreate). A job delete cascades its operations. A machine referenced by an operation cannot be deleted until the operation eligibility is edited. Sample records are tagged individually, and sample removal refuses to remove manually entered operations that depend on them.

Schedule-generation requests may include `search_options: { max_expansions, max_seconds, weights }`; the chosen limits and cost weights are stored with the input snapshot and each search result. Dynamic-reschedule requests may send the same `search_options` alongside `algorithm_name`; the revised run persists its own measured state counts and status. See `/docs` for the complete validated request/response schemas.

## Automated tests

From the repository root:

```bat
cd backend
.venv\Scripts\activate.bat
pytest
```

From a separate repository-root terminal:

```bat
corepack pnpm test
corepack pnpm typecheck
corepack pnpm build
```

Backend API and migration tests use isolated in-memory or disposable SQLite (and API tests disable application-startup migrations), so they do not read or write the shared managed database. The Python suite covers strict MySQL/PostgreSQL TLS enforcement, recorded/additive migrations and safe backfills, dispatch rules, all five search methods, the admissible heuristic, canonical duplicate-state detection, expansion- and time-limit termination without partial schedules, knowledge/planning constraints, maintenance and capability filters, persisted statistics, CRUD, metrics, recommendation ranking and stale snapshots. End-to-end API regressions load the opt-in automotive sample, check all three component routes and planning facts/actions, generate A*/FCFS schedules, and apply A*-searched breakdown and urgent-order revisions while verifying the parent run remains unchanged. Separate rescheduling tests cover every event, production progress locking, outage/delay constraints, safer machine alternatives, urgent-order persistence after feasibility, event history, schedule stability and infeasible rollback. Frontend interaction tests cover empty and opt-in sample states, bounded-search request payloads, persisted search evidence and automotive route details, and the original/revised dynamic-event view.

Latest local checks: `pnpm build` succeeded; `pnpm test` passed (8 tests across 4 files); `backend/.venv/bin/python -m pytest -q backend/tests` passed (51 tests; one upstream Starlette/AnyIO deprecation warning); `pyright --project pyrightconfig.json` reported 0 errors; and Python compile-only validation passed. The backend end-to-end tests use isolated SQLite. Docker image build was not run in this Sandbox.

## Deployment — Vercel frontend + Render FastAPI backend

1. Create an empty GitHub repository (or equivalent Git host), then from the project root initialize/push this source tree using that host's documented authentication. With GitHub CLI (`gh`) already authenticated, an example is `git init && git add . && git commit -m "Build ForgeIQ manufacturing scheduler" && gh repo create forgeiq --source=. --public --push`. Choose `--private` if the source or manufacturing configuration is confidential. Never add `.env`, database files or credentials to Git.
2. Create a managed PostgreSQL database in Render (or a PostgreSQL provider that supplies a trusted server certificate). Configure the API service's server-side `DATABASE_URL` with its private connection string and provide the provider's trusted CA through `sslrootcert` when it is not in system roots. The app normalizes `postgres://`/`postgresql://` URLs to SQLAlchemy's psycopg driver and enforces `sslmode=verify-full`.
3. Create a Render Docker web service using this repository's `Dockerfile`; set health check path to `/api/health`. Render supplies `PORT`; the container listens on that value (default 3000). Attach the persistent Postgres service/connection URL rather than relying on container-local SQLite.
4. Set `CORS_ORIGINS` on the backend to the exact Vercel production origin (for example `https://your-forgeiq-project.vercel.app`) plus any explicitly needed preview origins. Do not use `*` in production.
5. Create a Vercel project from the repository. Use install command `corepack pnpm install --frozen-lockfile`, build command `corepack pnpm build`, root directory `.`, and output directory `frontend/dist`. Set the browser-safe `VITE_API_URL` to the deployed API origin, e.g. `https://your-forgeiq-api.onrender.com`, with no trailing slash.
6. Set `DATABASE_URL` and `CORS_ORIGINS` only as protected server environment values. Do not expose DB credentials through `VITE_*`. After changing backend CORS, restart/redeploy the API and verify `/api/health`, `/api/v1/health` and a browser CRUD request.

For a single-container deployment rather than separate Vercel/Render services, build the React bundle into `frontend/dist` and let FastAPI serve both the UI and APIs as in the Dockerfile. Configure persistent PostgreSQL all the same. The local SQLite default is `backend/data/forgeiq.db` (container path `/app/backend/data/forgeiq.db`); container-local file writes are not durable. Mount durable storage there if deliberately deploying SQLite; otherwise do not use SQLite on an ephemeral filesystem.

## AI Intelligence Layer (optional, additive)

ForgeIQ includes an AI Intelligence Center, a search lab, a captured state-space explorer, measured scheduling comparisons, deterministic agents, and an illustrative Bayesian risk view. The search lab runs the existing bounded search algorithms; optional instrumentation captures actual root/generated/expanded/duplicate/goal/infeasible states and their transitions. Selecting a captured node is a view-only operation and does not rerun search.

The additive API endpoints are `/api/v1/ai-center`, `POST /api/v1/ai-search`, `GET /api/v1/ai-search-traces/{trace_id}`, `POST /api/v1/ai-recommendations`, `POST /api/v1/agents`, and `GET|POST /api/v1/bayesian-risk`. Search can read current records or a saved schedule input snapshot. Results are ranked only when complete and feasible, using the selected schedule objective; search `g/h/f` values are not treated as equivalent cross-method business objectives.

Search traces and agent activity are bounded process-local memory and disappear on backend restart; they are not shared across multiple workers. Bayesian conditional probabilities are illustrative assumptions, not learned or validated against manufacturing failure history. Risk is advisory and never changes machine availability or schedules. Agents are deterministic and read-only. Any schedule-changing action remains in the existing dynamic-rescheduling workflow and requires operator action.

### Demonstration

1. Load explicitly labelled demo data or enter manufacturing records, then check jobs, machines, operations and capabilities.
2. Open **AI Search Lab**, select current data or a saved-run snapshot, scenario, objective and method(s), then run once.
3. Inspect measured feasibility, objective, runtime, expansion/generation/duplicate counts, termination and optimality; open **State-Space Tree Explorer** to inspect the captured action and state values. Observe the display cap and truncation indicator.
4. Open **Scheduling Intelligence** to compare scenario-applicable methods using measured business metrics.
5. Run **Intelligent Agents** and review read-only evidence. Continue to Dynamic Rescheduling only after explicit confirmation; inspect and submit the existing workflow separately.
6. Change evidence in **Bayesian Risk Analysis**, inspect the posterior and assumptions, and treat the result as illustrative decision support only.

No database migration or new dependency is required. Install the existing backend requirements in a local environment with `python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt`; run `backend/.venv/bin/python -m pytest -q backend/tests` and the existing `pnpm test`, `pnpm typecheck`, `pnpm build` commands from the repository root.
