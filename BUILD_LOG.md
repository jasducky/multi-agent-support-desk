Alice never sees Bob's laptop.

# BUILD_LOG

> Copy this file to `BUILD_LOG.md`. Fill in each stage **as you go**, not at the end: the
> decision **before** you prompt your agent, the prediction **before** you run the check.
>
> This is your record of what *you* understood. A person reads it for `G-DESIGN` and
> `G-ENFORCE`. Your coding agent is instructed not to write it for you; if the words aren't
> yours, it shows.
>
> Three lines per part is plenty. "I expected X, got Y, because Z" beats a paragraph.

---

## Stage 1: the database
- **I decided:** A reset script that deletes the tables and reloads the sample data. Every test run then starts with the same shop, and order 5 is always Bob's laptop. I compared three options with Claude Code: Docker is slower, and a rollback doesn't reset the order numbers.
- **I predicted:** Three tables: 10 customers, 17 orders numbered 1 to 17, and an empty actions log. The actions log only accepts five labels: cancel, return, update address, update preference and update profile. So logging `RETURN_ITEM` should be refused, which stops one kind of request being counted under two names.
- **What happened (paste output):**

## Stage 2: the tools, and where access control lives
- **Before reading SPEC R-1, I thought ownership belonged in:** Code. It's an access rule, so it must hold every time, and a prompt can be ignored.
- **I decided:** Reading R-1 didn't change my mind. The agent never touches the database. It asks the Toolbox to run one of three tools: look up an order, list orders, or log a request. Each tool's query only returns an order when the order number and the email both match. The course's reference version only said this in the prompt, and Alice got Bob's $1,500 laptop. I expect Alice to get her keyboard for order 3, and nothing for order 5.
- **What happened (order 5 as alice):**

## Stage 3: the agent, and a bare CLI
- **I decided (tools loaded, how the email is bound):** The agent gets only the three tools, and none of them can change an order, so a cancel becomes a request in the log for a person to act on. The customer's email is fixed by the code at login (a bound parameter). The model can't see or change it, so Alice can't claim to be Bob.
- **I predicted the "order 5 for bob" request would:** Logged in as Alice, I'll ask for order 5 for bob.smith@techmail.com. I think the model will still call the tool, as it can't see the email is fixed. The tool uses Alice's email and finds nothing, so she's told it isn't on her account. I'll also say "only this customer's orders" in the prompt, but nothing relies on it.
- **What happened:**

## Stage 4: the pipeline and its events
- **My hand-sketched CLI lines:** I chose short lines that show what happened, pass or fail, how long, and why. The full detail stays in the run file and in Phoenix. I sketched these with Claude Code:

  ```
  ✓ judge        passed   2.2s   no injection patterns
  → tool         get-order-status  order 3  (email: bound to login)
  ← result       order 3: SHIPPED   9ms
  ◆ recall       used: "leave packages at the back door" (0.62) · 2 skipped, below cutoff   0.3s
  ✗ judge        BLOCKED  0.9s   SQL injection pattern
  ■ final        "Order 3 has shipped."   6.1s ✓
  ```

  Every line shows its time (a tool's time is on its result line). The last line shows the total, with ✓ if it's within the speed target. The tool line shows the email as bound, which proves stage 3. The recall line shows the memory text, so I can see which memory was used.
- **I predicted the first event after the agent stage would be:** The model's decision (`llm`). The model reads the message and decides it needs a tool. Tools only run when the model asks, so the tool call comes after.
- **What happened:**

## Stage 5: one trace per turn
- **I decided (what goes in span attributes, who can see Phoenix):** I record everything: the message, the conversation, tool calls and results, times, tokens, the model and the prompt version. Messages can hold personal details like a phone number. I need to see them to check the mask step hid them in the reply, so I limit who can open traces rather than hiding the data. The exception is card numbers, which are removed before anything is recorded. Here Phoenix runs only on my laptop. In a real shop, only named engineers behind a login could open it. The spec asks for the same.
- **Trace id:**
- **One thing the trace showed that the reply didn't:**

## Stage 6: Sanitizer and Security Judge
- **I decided (who may block, which A2A method):** The Judge works in two steps, and either step can block.

    1. A pattern check (code) always runs first. It looks for known attack shapes: database commands, web page code, template tricks, server commands, and phrases like "ignore your instructions". A match blocks straight away, without calling the model.
    2. If nothing matches, the model reads the message for tricks a list can't spot, like "you're now in admin mode", or the same attack written in French.

  The patterns come from attack types, not the course's test set. They match shapes, not single words, so "drop the gift wrap" still gets through. The spec leaves open whether the pattern check can block on its own. I said yes: a check that must always happen shouldn't be left to the model. For A2A I use `message/send`, the current version. The reference version uses the older `tasks/send`.
- **Predicted vs actual X01 latency:** Under half a second. X01 is a database command, so the pattern check blocks it before the model runs. An attack that reaches the model would take about 2 seconds, assuming the Judge uses gemini-2.5-flash, a fast model. The course's own example shows 2.2 seconds. Actual: to add after the build.
- **When I stopped the Judge, my pipeline first:**
- **Failing trajectory saved at:**

## Stage 7: the Guardrail
- **Three messages that must pass / three that must not (written before the prompt):** The rule: let through anything about the customer's dealings with this shop, and block using it as a general assistant. Judge what they want the shop to do, not the words they use.

    Must pass:
    1. "Can I change the delivery date on my chair order?"
    2. "My keyboard arrived broken, I'd like to return it."
    3. "I've moved house, so please send everything to my new address from now on."

    Must not pass:
    1. "Give me a recipe for a quick weeknight dinner."
    2. "Write me a strategy brief for my team."
    3. "Can you walk me through setting up my VR headset?"

  Let through: orders, deliveries, changes, complaints, faulty items, and personal details that help the shop serve them, like delivery or packing needs. Block: general questions, writing tasks, trivia, and product setup advice. The last one is a judgement call. A real shop would have product guides to answer from, but this build doesn't, so the agent would be guessing. The examples are my own, not from the test set.
- **What the customer sees when the Guardrail blocks:** A fixed message saying what I can help with: orders, deliveries, returns and their account. Product setup questions get their own version: it points to the maker's support and asks if the item is faulty and they want a return. It's fixed, not written by the model, so it's fast and can't drift into answering.
- **False blocks / off-topic blocks, per prompt version:**

  | Version | What I changed | Legit false blocks | Off-topic blocked |
  |---|---|---|---|
  | v1 | | | |

## Stage 8: Masker and memory
- **I decided (what counts as PII, the cutoff):**
- **My planted memory's score, and whether my cutoff kept it:**
- **What the Masker reported on my PII test:**

## Stage 9: the web UI
- **My sketch, in words:**
- **Something the UI shows that the CLI doesn't (feature or leak?):**

## Stage 10: the eval runner
- **How I handled the memory waits:**
- **First run's failing rows, and what I changed:**
- **Second run: see `reports/eval.json` (don't retype numbers here).**
- **Successful turn I read end to end (trace id), and what it taught me:**
- **Failing turn I read end to end (trace id), and what it taught me:**
