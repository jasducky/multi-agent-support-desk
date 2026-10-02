# Submission: multi-agent support desk

A summary of my Assignment 3 submission for the FDE bootcamp: the links, the eval results, the traces named by the run and the one threshold I missed.

| | |
|---|---|
| 🎬 Demo video (3:56) | [demo.mp4](demo.mp4) |
| 📊 Eval report, written by the runner | [reports/eval.json](../reports/eval.json) |
| 🖥️ Terminal output of that run | [reports/eval-run-output.txt](../reports/eval-run-output.txt) |
| 📐 Design | [DESIGN.md](../DESIGN.md) |
| 📓 Build log | [BUILD_LOG.md](../BUILD_LOG.md) |

## Eval results

**18 of 19 checks passed** in the final run (01 Oct 2026, 15:24 UTC, 128 turns, 557 s, model `gemini-2.5-flash`, code at commit `9a608d4`). Red lines crossed: none.

This page is generated from `reports/eval.json` by `submission/build_readme.py`, so no number here is typed by hand.

### Speed

| | Check | Result | Target | Test messages |
|---|---|---|---|---|
| ✅ | A typical answered question <br><sub>`T-LAT-P50`</sub> | **4.5 s** | at most 8.0 s | 12 |
| ✅ | The slowest answered questions (95th percentile) <br><sub>`T-LAT-P95`</sub> | **6.8 s** | at most 15.0 s | 12 |
| ✅ | The slowest blocked messages (95th percentile) <br><sub>`T-LAT-BLOCK-P95`</sub> | **3.2 s** | at most 5.0 s | 29 |
| ✅ | Turns that ended in an error <br><sub>`T-ERR`</sub> | **0%** | at most 2% | 115 |

### Safety

| | Check | Result | Target | Test messages |
|---|---|---|---|---|
| ✅ | Attacks blocked <br><sub>`T-ATTACK-BLOCK`</sub> | **100%** | at least 90% | 30 |
| ✅ | Normal questions wrongly blocked <br><sub>`T-LEGIT-FALSE-BLOCK`</sub> | **0%** | at most 5% | 30 |
| ✅ | Off-topic messages blocked <br><sub>`T-OFFTOPIC-BLOCK`</sub> | **100%** | at least 80% | 15 |
| ✅ | Replies showing another customer's orders <br><sub>`T-LEAK`</sub> | **0** | 0 | 10 |

### Getting it right

| | Check | Result | Target | Test messages |
|---|---|---|---|---|
| ✅ | Order questions answered correctly from the database <br><sub>`T-ORDER-CORRECT`</sub> | **100%** | at least 90% | 12 |
| ✅ | Requests recorded with an allowed action type <br><sub>`T-ACTION-LOGGED`</sub> | **100%** | at least 90% | 8 |
| ✅ | Calls to any tool that changes an order <br><sub>`T-MUTATE`</sub> | **0** | 0 | 128 |

### Memory

| | Check | Result | Target | Test messages |
|---|---|---|---|---|
| ✅ | Memories fetched per question <br><sub>`T-MEM-TOPK`</sub> | **5** | 5 | 1 |
| ✅ | Lowest score a memory needs to be used <br><sub>`T-MEM-MINSCORE`</sub> | **0.25** | 0.25 | 1 |
| ✅ | Longest memory allowed (characters) <br><sub>`T-MEM-MAXCHARS`</sub> | **500** | 500 | 1 |
| ✅ | Wait between saving a fact and asking about it (seconds) <br><sub>`T-MEM-WAIT`</sub> | **120** | at least 120 | 1 |
| ❌ | Saved facts found again when the customer asked <br><sub>`T-MEM-RECALL`</sub> | **50%** | at least 80% | 10 |

### Traces

| | Check | Result | Target | Test messages |
|---|---|---|---|---|
| ✅ | Turns with exactly one trace <br><sub>`T-TRACE-ONE`</sub> | **100%** | 100% | 115 |
| ✅ | Passing turns with every required step in the trace <br><sub>`T-TRACE-SHAPE`</sub> | **100%** | 100% | 115 |
| ✅ | Turns whose steps arrived in the right order <br><sub>`T-EVENT-ORDER`</sub> | **100%** | 100% | 115 |

## Traces named by the run

| | Trace id | What happens |
|---|---|---|
| ✅ Success | `94fd180a88e1d1b2c31df2c7a5939c2b` | Alice asks for the status of order 3 and gets a clear answer, with every step passing |
| ⚠️ Failing | `5feaf7df08997fd9571235694eaddf97` | The pipeline could not reach the Security Judge, so the turn stops with an error rather than answering without the check. The run file is in [runs/failing/](../runs/failing/) |

## The one threshold I missed

Memory recall was 0.5 against a target of 0.80. I kept the memory cut-off at 0.25, because lowering it to 0.15 would pass the test but would also let unrelated memories in, and `DESIGN.md` explains this under Trade-offs.
