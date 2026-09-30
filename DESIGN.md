# DESIGN

> Copy this file to `DESIGN.md` and answer it **before you write code**. Revise it as you
> learn, but keep the first version in git history. A stranger grades it (`G-DESIGN`), so
> write for someone who has never seen your code. The five headings are fixed; keep them.

## Components

Separate programs on my laptop: the Postgres database, the MCP Toolbox that runs the three tools (port 5000), the Security Judge (port 10002), the Data Masker (port 10003) and Phoenix for traces (port 6006).

One main program, the pipeline, runs each message through its steps: sanitize, then the Judge, the Guardrail, memory recall, the support agent, the Masker and memory save. The command line and the web page are two ways into it.

Outside services: Gemini, the model, and Mem0, the memory store.

Each check is a separate part with its own job and only the access it needs, so a failure is easy to trace to one place. The Judge and the Masker are hygiene checks that any product would need, so they are their own programs that other products could share. The Guardrail's rule is specific to this shop, so it stays inside the shop's program.

## Responsibilities

Who stops a customer seeing someone else's orders: two parts together. The tool's database query in the Toolbox only returns an order when the order number and the email both match. The pipeline fixes that email to the logged-in customer at login, so the model can't change it. (Exact file and line to add after the build.)

Who holds the API keys: only the programs that call an outside service. The pipeline, the Judge and the Masker hold the Gemini key, and the pipeline holds the Mem0 key. The Toolbox holds the database password. Keys live in a .env file that is kept out of git, never in the code. The model never sees them, and the web page never gets one, as anything sent to a browser can be read.

Who stops a turn that goes over budget: the pipeline. It is the only part that sees every step of a turn, so it counts the tool calls, tokens and time, and stops the turn when one goes over the limit.

> (To do: the rules table.) For every rule in SPEC §11, say whether it is enforced **in code**, **in a
prompt**, or **both**, and why. This table is the core of `G-ENFORCE`.

## Communication

How does a message travel from the CLI or browser to the database and back? Name each hop's
protocol (function call, MCP, A2A JSON-RPC, HTTP, NDJSON). Which A2A method did you
implement, and what does a verdict look like on the wire?

## State

What is stored, where, and for how long: sessions, memories, traces, run logs, the action
log? Which of them contain customer data, and who can read each one? What happens to
memory when a customer's order changes after the memory was saved?

## Trade-offs

What did each guard cost you in latency (from your traces), and was it worth it? Did you
make the Guardrail fail closed, and what does that cost when Gemini is slow? If you changed
`T-MEM-MINSCORE` or argued against any threshold, give the evidence here, and keep the
original gate in your report.
