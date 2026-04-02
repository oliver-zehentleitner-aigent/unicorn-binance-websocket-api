# TASKS.md — Development Backlog

Tasks collected from codebase analysis (2026-04-01). Ordered by priority within each group.

---

## High Priority

### [ ] Rebuild listen key handling — remove REST-based approach
- Current REST-based listen key ping (`_ping_listen_key` in `manager.py`) is obsolete
- Rebuild using the WebSocket-native approach
- Remove `restclient.keepalive_listen_key()` call path
- Affects: `manager.py:_ping_listen_key()`, `restclient.py`

### [ ] Remove check_lucit_collector + Icinga support
- Remove `get_latest_release_info_check_command()` and `get_latest_version_check_command()` from `manager.py`
- Remove `last_update_check_github_check_command` state
- Remove any Icinga/monitoring plugin code (REST server routes)
- Out-of-scope for this library

### [ ] Add rate-limit backoff strategy (429 handling)
- Currently: 429 response from Binance crashes the stream (`manager.py:_run_socket()`)
- Implement exponential backoff before restart on 429
- Log clearly how long the backoff will be
- Consider a global rate-limit state shared across streams

---

## Medium Priority

### [ ] Fix subscribe_to_stream — send delta only + proper reconnect re-subscribe (issue #374 follow-up)
- Currently `subscribe_to_stream()` sends the **full current subscription list** on every call, not just the delta
- This bloats the payload queue and causes Binance subscription count to diverge from UBWA's internal count
  when combined with send timeouts or the split_payload bug (now fixed)
- Two changes needed together:
  1. `subscribe_to_stream()` / `unsubscribe_from_stream()`: send only the **delta** (new/removed streams), not the full list
  2. On **reconnect**: explicitly re-subscribe all markets from `stream_list` via the payload queue, since a new
     WebSocket connection has no prior state — the URI only carries the original creation-time channels/markets
- Requires careful testing: reconnect scenarios, concurrent subscribe/unsubscribe calls, queue draining

### [ ] Replace stream_list dict entries with @dataclass
- `manager.py:_add_stream_to_stream_list()` — 30+ key raw dict per stream
- Create `StreamState` dataclass in new file `stream_state.py`
- Gives: type safety, IDE autocomplete, typo protection, easier refactoring
- No behavioral change required

### [ ] Fix linear request_id scan in sockets.py
- `sockets.py:174–186` — scans raw JSON string for each pending request_id as substring
- O(n×m), false-positive-prone, runs on every received message for WS API streams
- Fix: parse JSON once, extract `id` field directly, use dict lookup

### [ ] Modernize SOCKS5 proxy using websockets native support
- Current implementation in `connection.py` manually creates a `socks.socksocket()` (PySocks) and passes it
  via `sock=` to `websockets.connect()` — a low-level workaround
- websockets 14 supports proxies natively via the `proxy` parameter in `connect()`
- Replace the manual PySocks socket setup with `proxy="socks5://user:pass@host:port"` (or similar)
- Allows removing the manual `netloc` parsing, `host:port` split, and `socks.socksocket` setup in `__aenter__`
- May allow simplifying or removing the PySocks (`socks`) dependency

### [ ] Remove wildcard imports
- `from .exceptions import *` in `manager.py`, `connection.py`, `sockets.py`
- Replace with explicit imports
- Enables proper static analysis with mypy/pyright

---

## To Discuss

### [ ] GitHub update check — make async or lazy
- `__init__` currently makes a synchronous HTTP request to `api.github.com` on every instantiation
- Options: (a) move to background thread, (b) make lazy (only on first explicit call), (c) remove entirely
- Decision needed before implementing

---

## Done / Accepted as-is

- **Thread-per-stream model** — intentional design. Isolation allows killing a thread+loop atomically. Works well in practice.
- **API secrets in stream_list** — acceptable for a developer-facing library
- **SSL verification flag** — acceptable for a developer-facing library
- **print() alongside logger** — critical errors are intentionally printed to stdout in addition to being logged, so operators see them even without a log setup
- **Remove DEX support** — done in PR #400
- **Upgrade websockets + Python 3.14 GIL support** — done in PR #401
- **Fix split_payload() returning None at multiples of 351** — done in PR #401 (issue #374)
- **Fix reconnect: clear payload queue + re-subscribe on restart** — done in PR #402 (issue #374)
