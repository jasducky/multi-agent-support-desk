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
- **I decided:** A reset script that deletes the tables and reloads the sample data. Every test run has to start with the same shop: the same customers and the same 17 orders, each with the same number, customer, product, status and total. I worked through the three options with Claude Code. A throwaway Docker database also gives the same shop, but it restarts the whole database on every run, so it's slower. A rollback is quick, but it doesn't put the order numbers back, so tests that name an order would be looking at the wrong one.
- **I predicted:** I expect three tables. The users table will have the 10 customers, each with their own ID and a unique email. The customer orders table will have the 17 orders from the sample data, numbered 1 to 17 in the same order and spread across those 10 customers. The actions log will start empty. It records what a customer asked for, and it should only accept the five agreed labels: cancel an order, return an order, update address, update preference and update profile. So when the check tries to log `RETURN_ITEM`, a near-miss for `RETURN_ORDER`, I expect the database to refuse it. That keeps the same request from being logged under different names, which would make counts like "how many returns this week" wrong.
- **What happened (paste output):**

## Stage 2: the tools, and where access control lives
- **Before reading SPEC R-1, I thought ownership belonged in:** Code. It's an access rule, so it has to be enforced every time, and a prompt is only an instruction that the model can skip or be talked out of.
- **I decided:** Reading R-1 didn't change my mind: ownership is enforced in code, not in the prompt. The agent never touches the database. It asks the Toolbox to run one of three tools: look up an order, list a customer's orders, or log a request. The code check sits in the SQL query behind each tool, which only returns an order when both the order number and the customer's email match (orders have no customer ID, so email is the link). The prompt can still say "only this user", but nothing relies on it. I worked through this with Claude Code after reading about the incident in the course's reference version, where Alice asked for order 5 and got Bob's $1,500 laptop because only the prompt said it. Making sure the email comes from the login, not the model, is stage 3. So I expect Alice asking for order 3 to get her keyboard, and Alice asking for order 5 to get nothing.
- **What happened (order 5 as alice):**

## Stage 3: the agent, and a bare CLI
- **I decided (tools loaded, how the email is bound):** The agent loads only its own group of three tools: look up an order, list the customer's orders, and log a request. All three only read orders or write to the request log, so if a customer asks to cancel, the agent logs the request and a person or another system acts on it later. The customer's email is fixed by the code at login as a bound parameter. The model never sees that field and can't change it. It only fills in what the customer asked about, such as the order number or the kind of request. I worked through this with Claude Code. If the model filled in the email, Alice could say she was Bob and get his order back, which is the incident in the course's reference version all over again.
- **I predicted the "order 5 for bob" request would:** Logged in as Alice, I'll ask the agent to look up order 5 for bob.smith@techmail.com. I think the model will most likely still call the look-up tool with order 5, as it can't see that the email is fixed to Alice. The tool runs with Alice's email and finds nothing, and the agent tells her the order isn't on her account, with nothing about Bob's laptop. I'll also put a line in the agent's instruction to only help with the logged-in customer's own orders, but the design doesn't rely on it. The agent's recorded steps from stage 4 will show whether the tool was called.
- **What happened:**

## Stage 4: the pipeline and its events
- **My hand-sketched CLI lines:** I chose short lines that say what happened, whether it passed, how long it took and why. The full detail stays in the saved run file and in Phoenix. I sketched these with Claude Code:

  ```
  ✓ judge        passed   2.2s   no injection patterns
  → tool         get-order-status  order 3  (email: bound to login)
  ← result       order 3: SHIPPED   9ms
  ◆ recall       used: "leave packages at the back door" (0.62) · 2 skipped, below cutoff   0.3s
  ✗ judge        BLOCKED  0.9s   SQL injection pattern
  ■ final        "Order 3 has shipped."   6.1s ✓
  ```

  Each line shows its own time (the tool's time shows on its result line, once the answer comes back), and the last line of a turn shows the total with a tick if it is within the speed target or a warning if it is over, so I can see whether a turn is slow and which check made it slow. The tool line shows the email as bound, so every call proves my stage 3 decision. The recall line shows the memory text rather than a count, so I can see which memory was used without opening the file. The agent's reply is printed in full at the end of each turn.
- **I predicted the first event after the agent stage would be:** I expect the model's decision (the llm event) to come first. When the agent step starts, the model reads Alice's message and decides whether it needs a tool. The tools only run when the model asks for one, so its decision to call get-order-status comes first and the tool call follows it.
- **What happened:**

## Stage 5: one trace per turn
- **I decided (what goes in span attributes, who can see Phoenix):** I decided to record the full detail in the trace: the customer's message and the conversation so far, the tool calls and what they returned, the time, the tokens, the model and the prompt version. A message can carry personal details, such as a phone number, and I need to see them to check that the mask step hid them if they came back in the reply. So I control who can open the traces rather than hiding the data. The one exception is a card number, which a customer would only type by accident, and that gets removed before anything is recorded. In this build Phoenix runs only on my laptop with no login, so only I can see it. In a real shop I'd limit it to named engineers behind a login. I worked through this with Claude Code, and the course's spec takes the same position: it requires the message, the reply and the prompts in the trace.
- **Trace id:**
- **One thing the trace showed that the reply didn't:**

## Stage 6: Sanitizer and Security Judge
- **I decided (who may block, which A2A method):** I decided on a layered Judge that works in two steps, and either step can block on its own.

    1. The Judge always runs its pattern check, which is code. It looks for the shapes of known attacks: database commands, web page code, template tricks, commands aimed at the server, and fixed phrases such as "ignore your instructions". If it finds one, the message is blocked straight away and the model is never called, so known attacks are stopped quickly and the same way every time.
    2. If the pattern check finds nothing, the model always reads the message. It looks for attacks a list can't recognise, such as someone claiming to be in admin mode, or "ignore your instructions" written in French or spaced out. If it judges the message an attack, it blocks it and gives the reason.

  The pattern list is built from attack categories, not copied from the course's test set, so it catches new attacks of the same shape rather than only the ones being tested. It matches attack shapes rather than single words, so "can you drop the gift wrap" still gets through. The pattern check is the Judge's tool, and the Judge always runs it first rather than waiting for its model to decide to. The spec leaves open whether the pattern tool can block without the model. I decided it can, because a check that must always happen can't be left to the model to remember, and waiting for the model would slow down blocking an obvious attack. The model can also call the same check itself when it is reading something borderline.

  For A2A I'm using message/send, the current version of the standard. The course's reference version uses the older tasks/send, and I'd only pick that to work with an existing service built on it. I worked through this with Claude Code.
- **Predicted vs actual X01 latency:** I predict X01 is blocked in under half a second, because it is a database command that the Judge's pattern check catches before its model is ever called. An attack that gets past the pattern check would take about 2 seconds, since the model has to read it. I'm assuming the Judge uses gemini-2.5-flash, the same model as the support agent, which is a fast model built for short answers like the Judge's allow or block. The course's own example of a Judge step that used the model shows 2.2 seconds. I will add the actual time after the build.
- **When I stopped the Judge, my pipeline first:**
- **Failing trajectory saved at:**

## Stage 7: the Guardrail
- **Three messages that must pass / three that must not (written before the prompt):**
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
