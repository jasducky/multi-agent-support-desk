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
- **I decided (tools loaded, how the email is bound):**
- **I predicted the "order 5 for bob" request would:**
- **What happened:**

## Stage 4: the pipeline and its events
- **My hand-sketched CLI lines:**
- **I predicted the first event after the agent stage would be:**
- **What happened:**

## Stage 5: one trace per turn
- **I decided (what goes in span attributes, who can see Phoenix):**
- **Trace id:**
- **One thing the trace showed that the reply didn't:**

## Stage 6: Sanitizer and Security Judge
- **I decided (who may block, which A2A method):**
- **Predicted vs actual X01 latency:**
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
