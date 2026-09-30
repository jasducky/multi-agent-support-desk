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

How each of the course's rules (SPEC §11) is enforced:

| Rule | Code or prompt | Why |
|---|---|---|
| R-1. Customers only see their own orders | Code | The database query checks the email. A prompt could be ignored |
| R-2. Anything that must happen every time is built into the steps | Code | A model can forget an instruction. A step always runs |
| R-3. The agent has no tool that changes an order | Code | It only gets the three tools, so a cancel becomes a request |
| R-4. If a check stops working, the message is stopped with an error | Code | Otherwise a broken check would let everything through |
| R-5. Only save what the customer said | Code | The agent's own replies are never saved as memories |
| R-6. The guardrail only lets through questions this shop's support desk should answer | Prompt | No code can tell a support question from any other, so the guardrail works it out from instructions I write. Those instructions have to describe this shop's kinds of questions, with real examples. Generic ones got it wrong in the course's version: they blocked "leave packages at the back door" and let a poem through |
| R-7. Memories that are too long are thrown away | Code | A length check before a memory is used |
| R-8. A check only changes what it is meant to | Code | The masker hides the listed details and nothing else |
| R-9. The Judge always says clearly "allow" or "block" | Code | Its answer has a fixed shape, so silence can't be mistaken for "safe" |
| R-10. Traces are kept after a restart | Code | Phoenix runs on its own and saves to disk |
| R-11. The action log only accepts the five set labels | Code | The database refuses anything else |

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
