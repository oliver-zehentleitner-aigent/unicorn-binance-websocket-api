# Stream loop (`sockets.py` / `connection.py`)

## `recv()` runs without timeout after the first receives - `stop_stream()` waits for the next message

**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer confirmation 2026-09-10; `connection.py` (`timeout_disabled`), git history: threshold `processed_receives_total > 3` predates commit `fd370d8a` (2024-03-27, which added the `timeout_disabled` flag), today `> 10`

`BinanceWebSocketApiConnection.receive()` wraps `recv()` in
`asyncio.wait_for(..., timeout=1)` only until a stream has more than 10
processed receives; from then on, as long as the stream has subscriptions,
it awaits `recv()` without a timeout. `stop_stream()` merely sets
`stop_request`, which `receive()` checks at the top of each call.
Consequence: on a stream that has subscriptions but currently receives
nothing, a stop (or crash request) takes effect only when the next message
arrives - or when the peer closes. Against Binance this is invisible because
data keeps flowing; it surfaced in the local-server unit test for the
websocket-library switch, where the test server had to send a heartbeat for
the manager to shut down.

**Reason:** deliberate. `wait_for()` costs a task plus a timer per message,
which is not wanted on the hot path once a stream is known to be alive. The
timed phase at the start exists for the opposite case: a loop that never
receives anything (bad subscription, dead endpoint) must still be stoppable,
so the first receives are polled with a 1 s timeout until the stream has
proven it delivers data.

**Accepted consequence:** the stop latency on an established but currently
idle stream is acceptable to the maintainer; not a bug.

**Rejected alternative:** keeping a (long) timeout permanently - rejected
because of the per-message overhead. Closing the websocket from
`stop_stream()` directly was not in contention.

## Per-message work in the loop that is not the transport - profiled

**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** profiling pass 2026-09-10: cProfile of the stream thread (300k aggTrade messages from the local replay server, picows) plus a cumulative ablation with lean replacements of the hot-path methods, both libraries, median of 3; benchmark harness `dev/test_websocket_library_benchmark.py`

The websocket-library benchmark showed a constant ~5 µs per message that
UBWA spends on top of either library (raw libraries 2-3 µs/msg, through UBWA
6-9 µs/msg). Profiling attributes it as follows, per received message:

- **18 `logger.debug(f"...")` calls** while debug logging is off. The
  f-string is built before `debug()` checks the level, ~0.1 µs each. 12 of
  them are `stream_list_lock was entered` / `Leaving stream_list_lock` pairs
  inside `set_heartbeat()`, `increase_received_bytes_per_second()` and
  `increase_processed_receives_statistic()`; the rest are entry logs of
  `receive()`, `is_stop_request()`, `is_crash_request()` (each with a
  `get_debug_log()` call) and the dispatch log in `start_socket()`.
- **7 lock acquire/release cycles** (`stream_list_lock` x5,
  `total_received_bytes_lock`, `total_receives_lock`), ~0.17 µs each.
- **Duplicate work:** `set_heartbeat()` runs twice per message (in
  `receive()` and at the top of the loop iteration), `is_stop_request()` and
  `is_crash_request()` twice (loop condition and `raise_exceptions()` inside
  `receive()`).
- `sys.getsizeof(str(msg))` for the byte statistics (~0.1 µs, and it counts
  the str object header, not the payload).

**Ablation, small messages (0.2 KB), through the full stack, `raw_data`:**

| Stage (cumulative) | websockets msgs/s | CPU µs/msg | picows msgs/s | CPU µs/msg |
|---|---|---|---|---|
| A baseline | 119,880 | 8.41 | 166,906 | 6.07 |
| B no debug f-strings in the hot path | 160,992 | 6.28 | 268,185 | 3.82 |
| C + per-stream counters without `stream_list_lock` | 181,873 | 5.57 | 306,244 | 3.34 |
| D + heartbeat/stop/crash once per iteration | 181,969 | 5.56 | 344,516 | 2.93 |
| E + `len()` instead of `sys.getsizeof(str())` | 191,839 | 5.30 | 370,564 | 2.76 |

Raw libraries for reference: websockets ~3.0 µs, picows ~2.0 µs. Stage E
leaves ~0.8 µs of UBWA overhead with picows (dispatch cascade, one debug
call, counters) and ~2.3 µs with websockets.

**Lock-free counters, why it is safe and where it is not:** the per-stream
fields (`last_heartbeat`, `processed_receives_total`, the per-second
dicts) have a single writer, the stream's own thread; `_frequent_checks()`
in the manager thread reads them and prunes old timestamp keys after
`copy.deepcopy()` under the lock. A lock-free `+=` on an *existing* key is
safe; *inserting* a new timestamp key (once per second) while the manager
thread deep-copies the dict can raise "dictionary changed size during
iteration", so the insert path must keep the lock. That is the split the
ablation's stage C did not yet make - the production change must.

**Status of the change:** measured and proposed, not implemented; the
maintainer decides which stages to take (the debug-log removal touches
logs that may have been kept for lock debugging; `len()` changes the
reported byte statistics to payload size).
