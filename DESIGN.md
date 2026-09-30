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

A message from the web page or the command line goes through these steps, in this order:

1. The web page sends it to the pipeline over HTTP. The command line calls the pipeline directly.
2. Sanitize checks its length and characters, inside the pipeline.
3. The Judge checks it for attacks. It is a separate program, reached over A2A.
4. The Guardrail checks it is a question this shop's desk should answer, inside the pipeline. It asks Gemini over HTTP.
5. Recall fetches relevant memories from Mem0 over HTTP.
6. The support agent asks Gemini what to do over HTTP, and calls its tools through the Toolbox over MCP. The Toolbox runs the SQL query on Postgres.
7. The Masker checks the reply for other people's details, over A2A.
8. Save stores what the customer said in Mem0 over HTTP.
9. Every step is streamed back to the web page as it happens, one line per step (NDJSON).

For A2A I use message/send, the current version of the standard. A Judge verdict on the wire looks like this:

```json
{ "verdict": "allow", "reason": "no injection patterns" }
```

## State

| What is saved | Where | Customer data? | This build: how long, and who can read it | A real shop |
|---|---|---|---|---|
| The conversation | The main program's working memory | Yes | Until logout or restart. Nobody can open it. Copies are kept in the traces and run files | Saved to a database that support staff can look up, and kept as long as the shop's policy says |
| Long-term memories | Mem0 | Yes | Cleared for the test customers at the start of every test run. Readable by anything with the Mem0 key | Expire after 12 months (Mem0 supports an expiry date) |
| Traces | Phoenix, on disk | Yes, in full | Kept until I submit, as they're my evidence. Only I can open them, on my laptop | Kept 30 days. Only the product and technical team can open them |
| Run files | The runs folder | Yes | Kept until I submit. Only me | Kept 30 days. Only the product and technical team |
| The action log | The database | Yes | Reset before each test run. The Toolbox writes to it, and I can read it | Kept as long as order records. Staff who act on requests can read it |

If an order changes after a memory was saved, the database wins. Each memory is shown to the agent with the date it was saved (Mem0 already records this), and the agent's instructions say order facts come from the tools. If a memory and the database disagree, for example a cancel the customer asked for last week that never happened, the agent answers from the database, mentions the earlier request and when it was made, and logs a new request so someone follows it up. The agent can't read the action log itself, so it only spots this through memory.

## Trade-offs

What each check costs in time: to add after the build, from the traces.

If the Guardrail can't get a clear answer from Gemini, the message is stopped with an error rather than let through. The cost is that a customer may wait, get an error and have to try again. If Gemini is fully down, this costs nothing extra, as the support agent couldn't answer either. It matters when Gemini is only partly working. Letting messages through then would bypass the Guardrail, so requests that aren't about support, like recipes, would get answered and cost tokens and money. Someone could even make the Guardrail fail on purpose to get past it.

I kept the memory cut-off at 0.25, the course's own figure. Each memory gets a score for how well it matches the customer's message, and only memories scoring 0.25 or more are given to the agent. Set it too high and useful memories are missed, so customers have to repeat themselves. Set it too low and unrelated memories get in and muddle the answer. In the course's own tests, a real preference scored 0.30 and unrelated chatter scored below 0.25, so 0.25 sits between them. Support questions are usually about one recent issue, which should match well. I'll check it against my planted memory's score after the build and only change it if that shows a problem.
