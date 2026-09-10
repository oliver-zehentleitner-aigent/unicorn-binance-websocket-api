# WebSocket library: `websockets` (default) or `picows`

## Integrated via `picows.websockets`, not via the picows core API

**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** branch `feature/websocket-library-picows`, benchmark `dev/test_websocket_library_benchmark.py`

`BinanceWebSocketApiManager(websocket_library="picows")` swaps the transport
for the whole manager instance. The integration goes through
`picows.websockets` (picows >= 2.0.0), which is a drop-in replacement of the
`websockets` client API: same `connect()` signature, same `recv()`/`send()`/
`close()` on the connection object, same exception names. All the selection
logic lives in `unicorn_binance_websocket_api/websocket_library.py`;
`connection.py` only asks it for the `connect()` callable and `manager.py`
catches both exception families.

**Reason:** UBWA's per-stream loop (`sockets.py`) is written against the
`websockets` API - `await recv()` wrapped in `asyncio.wait_for()`, one
coroutine per stream in its own thread/event loop. Reusing that path means
zero duplicated stream logic and no second code path to keep in sync.

**Rejected alternative:** a "native" integration on picows' core API
(`ws_connect()` + a `WSListener` with `on_ws_frame()` callbacks). It would
avoid the pull-based `recv()` queue and the asyncio wake-up per message, and
is where picows gets its headline numbers. It was rejected *for now* because
it is a second connection implementation: a callback-to-coroutine bridge
(queue or futures) that has to reproduce `wait_for()` cancellation semantics,
fragmented-frame reassembly, close-handshake and ping/pong handling that
`picows.websockets` already provides. The measured gain of the compat layer
inside UBWA is real but moderate (see below), and the remaining overhead is
mostly UBWA's own per-message work, not the transport - so the extra
complexity would not pay off until that is addressed.

**Revisit when:** UBWA's per-message pipeline (`sys.getsizeof(str(...))`
byte accounting, the `wait_for()` wrapper, the stats counters) is slimmed
down, or picows exposes a zero-copy path for `picows.websockets`.

## Why the picows exception classes are caught separately

**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** `picows/websockets/exceptions.py` (picows 2.1.3)

`picows.websockets.exceptions.ConnectionClosed` & co. are *not* subclasses of
the `websockets` exception classes, they only share the names. The manager's
restart logic therefore catches tuples
(`CONNECTION_CLOSED_EXCEPTIONS`, ...) built in `websocket_library.py`; the
picows classes are appended only when the package is importable.

## Fail loud on `picows` without the package

**Type:** decision
**Status:** active
**Evidence:** confirmed

Selecting `"picows"` without the optional dependency raises `ImportError`,
an unknown value raises `ValueError` - no silent fallback to `websockets`.
Follows the suite-wide "fail loud" rule: a deployment that thinks it runs
picows but silently runs websockets is a hidden configuration bug.

## SOCKS5 proxy path is shared

**Type:** decision
**Status:** active
**Evidence:** confirmed

Both libraries get the pre-connected PySocks socket via `sock=` +
`server_hostname=` (UBWA's existing SOCKS5 handling). For picows the
`proxy=None` kwarg is passed explicitly on that path, because
`picows.websockets.connect()` defaults to `proxy=True` (environment
`wss_proxy`/`https_proxy` lookup) and would otherwise try a second proxy hop
over the already tunneled socket. picows' own proxy support (`socks5://`
URLs via python-socks, HTTPS proxies still a draft in
[tarasko/picows#80](https://github.com/tarasko/picows/pull/80)) is
deliberately not used, so proxy behaviour is identical for both libraries.

## Benchmark results

**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `dev/test_websocket_library_benchmark.py`, run on the branch

Setup: `dev/test_websocket_library_benchmark.py`, Python 3.13.5, x86_64 Linux
(4 cores), websockets 16.0, picows 2.1.3, UBWA 2.15.2.dev. A picows based
replay server in a separate process pushes pre-serialized Binance shaped
messages as fast as it can; "CPU µs/msg" is the client process' CPU time
(`time.process_time()`) divided by messages, so the server's cost is
excluded. 3 runs each, median.

**Libraries driven directly (`async for msg in ws`, no UBWA):**

| Scenario | ~msg size | msgs | websockets msgs/s | picows msgs/s | picows speedup | websockets CPU µs/msg | picows CPU µs/msg |
|---|---|---|---|---|---|---|---|
| small_aggtrade | 0.2 KB | 300,000 | 326,982 | 493,206 | 1.51x | 3.1 | 2.0 |
| medium_kline | 0.3 KB | 150,000 | 316,559 | 491,393 | 1.55x | 3.2 | 2.0 |
| large_depth20 | 1.0 KB | 60,000 | 280,948 | 465,901 | 1.66x | 3.6 | 2.2 |
| xlarge_depth_diff | 9.1 KB | 30,000 | 143,760 | 283,667 | 1.97x | 7.0 | 3.5 |
| huge_ticker_arr | 453.9 KB | 600 | 5,842 | 6,698 | 1.15x | 172.5 | 140.7 |
| multiplex_mix | 0.2 KB | 120,000 | 304,762 | 470,529 | 1.54x | 3.3 | 2.1 |

**Through UBWA, `output_default="raw_data"` (callback receives the JSON string):**

| Scenario | ~msg size | msgs | websockets msgs/s | picows msgs/s | picows speedup | websockets CPU µs/msg | picows CPU µs/msg |
|---|---|---|---|---|---|---|---|
| small_aggtrade | 0.2 KB | 300,000 | 116,314 | 163,406 | 1.40x | 8.7 | 6.2 |
| medium_kline | 0.3 KB | 150,000 | 112,815 | 158,541 | 1.41x | 9.0 | 6.4 |
| large_depth20 | 1.0 KB | 60,000 | 96,835 | 135,253 | 1.40x | 10.5 | 7.8 |
| xlarge_depth_diff | 9.1 KB | 30,000 | 50,746 | 51,629 | 1.02x | 20.2 | 20.0 |
| huge_ticker_arr | 453.9 KB | 600 | 1,753 | 1,597 | 0.91x | 615.9 | 676.9 |
| multiplex_mix | 0.2 KB | 120,000 | 110,738 | 153,079 | 1.38x | 9.2 | 6.7 |

**Through UBWA, `output_default="dict"` (plus `orjson.loads()`):**

| Scenario | ~msg size | msgs | websockets msgs/s | picows msgs/s | picows speedup | websockets CPU µs/msg | picows CPU µs/msg |
|---|---|---|---|---|---|---|---|
| small_aggtrade | 0.2 KB | 300,000 | 108,738 | 146,053 | 1.34x | 9.3 | 6.9 |
| medium_kline | 0.3 KB | 150,000 | 101,532 | 135,117 | 1.33x | 10.0 | 7.5 |
| large_depth20 | 1.0 KB | 60,000 | 79,148 | 100,820 | 1.27x | 13.1 | 10.4 |
| xlarge_depth_diff | 9.1 KB | 30,000 | 22,118 | 23,302 | 1.05x | 46.1 | 43.2 |
| huge_ticker_arr | 453.9 KB | 600 | 357 | 397 | 1.11x | 2871.3 | 2617.6 |
| multiplex_mix | 0.2 KB | 120,000 | 86,168 | 113,088 | 1.31x | 11.8 | 9.0 |

**Live binance.com, 20 symbol multiplex + `!ticker@arr`/`!miniTicker@arr` + 10x `depth`, 60 s each, sequential:**

| Library | msgs/s | MB/s | CPU % of one core | CPU µs/msg |
|---|---|---|---|---|
| websockets | 441 | 0.20 | 8.7 | 198.1 |
| picows | 306 | 0.16 | 6.1 | 199.2 |

**Reading:**

- Small and medium messages (<= ~1 KB, the bulk of Binance traffic): picows
  ~1.4x throughput and ~30 % less CPU per message inside UBWA. Standalone the
  libraries are 1.5x-2x apart.
- >= ~10 KB (full `depth` diffs, `!ticker@arr`): parity inside UBWA (0.9x-1.1x,
  within run-to-run noise). Cost there is dominated by UTF-8 decoding of the
  payload plus UBWA's substring checks (`"error" in ...`, `"result" in ...`)
  and byte accounting over the whole message.
- UBWA adds a constant ~5 µs per message on top of either library
  (3.1 -> 8.7 µs for websockets, 2.0 -> 6.2 µs for picows). That is the
  bigger lever: the transport is at most a third of the per-message cost.
- Live at a few hundred msgs/s the numbers are identical (~198 µs CPU/msg for
  both) because the manager's fixed overhead (monitoring loops, per-stream
  event loops, keepalive) dominates; message rate differs between the two
  windows only because market activity differs. Library choice only matters
  for high-throughput consumers or CPU-bound hosts.
