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

## Per-message work in the loop that is not the transport

**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** `websocket-library.md` "Benchmark results"; code reading of `connection.py` / `sockets.py`

The benchmark for the websocket-library switch showed a constant ~5 µs per
message that UBWA spends on top of either library (raw libraries 2-3 µs/msg,
through UBWA 6-9 µs/msg). Not profiled yet; visible per-message work in the
code: `sys.getsizeof(str(...))` byte accounting plus three lock-protected
counters in `receive()`, the `wait_for()` wrapper on early receives,
substring checks (`"error" in`, `"result" in`, `userdata_subscribe_id in`)
over the raw JSON string, and the dispatch cascade in `start_socket()`.
Recorded so that a future optimization pass starts from the measurement
rather than from the transport.
