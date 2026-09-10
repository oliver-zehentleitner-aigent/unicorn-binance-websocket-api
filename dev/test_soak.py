#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# File: dev/test_soak.py
#
# Part of ‘UNICORN Binance WebSocket API’
# Project website: https://github.com/oliver-zehentleitner/unicorn-binance-websocket-api
# Github: https://github.com/oliver-zehentleitner/unicorn-binance-websocket-api
# Documentation: https://oliver-zehentleitner.github.io/unicorn-binance-websocket-api
# PyPI: https://pypi.org/project/unicorn-binance-websocket-api
#
# Author: Oliver Zehentleitner
#
# Copyright (c) 2019-2026, Oliver Zehentleitner (https://about.me/oliver-zehentleitner)
# All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

"""
Soak test: run a heavy live multiplex against Binance for hours with one
`websocket_library` and record health metrics once a minute.

Not part of CI. Streams (all on `--exchange`, default binance.com):

- `!ticker@arr` + `!miniTicker@arr`
- aggTrade / trade / depth20@100ms / kline_1m / bookTicker for the top
  `--symbols` USDT markets by 24h quote volume (fetched via REST at start)
- `depth@100ms` (diff depth) for the top 20 of those
- optional, when `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET`
  are set: a second manager on binance.com-testnet with a `!userData` stream
  and a WebSocket API stream that calls `get_server_time()` once a minute
  (return_response=True) - exercises the userData + WS API paths live.

Every minute one CSV row per run (messages, bytes, rate, reconnects, stream
statuses, seconds since last data per stream, RSS, CPU %, threads, error
count, WS API ok/failed), plus a signals log with every stream signal.

Usage:
    python3 dev/test_soak.py --library picows --hours 24 --out ./soak/picows
    python3 dev/test_soak.py --library websockets --hours 24 --out ./soak/websockets
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unicorn_binance_websocket_api.manager import (  # noqa: E402
    BinanceWebSocketApiManager,
)
import argparse  # noqa: E402
import csv  # noqa: E402
import logging  # noqa: E402
import platform  # noqa: E402
import psutil  # noqa: E402
import requests  # noqa: E402
import signal  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402


def top_usdt_symbols(count, exclude_stable=("USDCUSDT", "FDUSDUSDT", "TUSDUSDT")):
    tickers = requests.get(
        "https://api.binance.com/api/v3/ticker/24hr", timeout=20
    ).json()
    usdt = [
        t
        for t in tickers
        if t["symbol"].endswith("USDT") and t["symbol"] not in exclude_stable
    ]
    usdt.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
    return [t["symbol"].lower() for t in usdt[:count]]


class Soak:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.messages = 0
        self.bytes = 0
        self.last_data = {}  # stream_id -> time.time() of the last message
        self.signals = []
        self.api_ok = 0
        self.api_failed = 0
        self.stop = threading.Event()
        os.makedirs(args.out, exist_ok=True)
        self.signals_file = open(os.path.join(args.out, "signals.log"), "a")
        self.csv_path = os.path.join(args.out, "metrics.csv")
        self.process = psutil.Process()
        self.process.cpu_percent(interval=None)

    # --- callbacks (hot path: keep them cheap) ---------------------------------
    def on_data(self, data):
        # raw_data output -> `data` is the JSON string; UBWA prepends nothing
        with self.lock:
            self.messages += 1
            self.bytes += len(data)

    def on_signal(
        self, signal_type=None, stream_id=None, data_record=None, error_msg=None
    ):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {signal_type} stream_id={stream_id} error_msg={error_msg}\n"
        try:
            self.signals_file.write(line)
            self.signals_file.flush()
        except ValueError:
            pass  # file already closed during shutdown

    # --- setup -----------------------------------------------------------------
    def start(self):
        args = self.args
        self.ubwa = BinanceWebSocketApiManager(
            exchange=args.exchange,
            websocket_library=args.library,
            output_default="raw_data",
            process_stream_data=self.on_data,
            process_stream_signals=self.on_signal,
            warn_on_update=False,
            disable_colorama=True,
        )
        symbols = top_usdt_symbols(args.symbols)
        self.streams = {
            "arr": self.ubwa.create_stream(
                ["arr"], ["!ticker", "!miniTicker"], stream_label="arr"
            ),
            "markets": self.ubwa.create_stream(
                ["aggTrade", "trade", "depth20@100ms", "kline_1m", "bookTicker"],
                symbols,
                stream_label="markets",
            ),
            "depth": self.ubwa.create_stream(
                ["depth@100ms"], symbols[:20], stream_label="depth"
            ),
        }
        self.testnet = None
        key, secret = os.getenv("BINANCE_TESTNET_API_KEY"), os.getenv(
            "BINANCE_TESTNET_API_SECRET"
        )
        if key and secret:
            self.testnet = BinanceWebSocketApiManager(
                exchange="binance.com-testnet",
                websocket_library=args.library,
                output_default="dict",
                process_stream_data=self.on_data_testnet,
                process_stream_signals=self.on_signal,
                warn_on_update=False,
                disable_colorama=True,
            )
            self.streams["userdata"] = self.testnet.create_stream(
                ["arr"],
                ["!userData"],
                api_key=key,
                api_secret=secret,
                stream_label="userData",
            )
            self.streams["api"] = self.testnet.create_stream(
                api=True, api_key=key, api_secret=secret, stream_label="api"
            )
        print(
            f"soak {args.library} on {args.exchange}: {len(symbols)} symbols, streams={list(self.streams)}, "
            f"testnet={'yes' if self.testnet else 'no (BINANCE_TESTNET_API_KEY not set)'}",
            flush=True,
        )

    def on_data_testnet(self, data):
        with self.lock:
            self.messages += 1

    def manager_of(self, name):
        return self.testnet if name in ("userdata", "api") else self.ubwa

    # --- metrics ---------------------------------------------------------------
    def api_probe(self):
        if self.testnet is None:
            return
        try:
            response = self.testnet.api.spot.get_server_time(
                stream_id=self.streams["api"], return_response=True
            )
            if response and response.get("status") == 200:
                self.api_ok += 1
            else:
                self.api_failed += 1
        except Exception:
            self.api_failed += 1

    def row(self, previous):
        now = time.time()
        with self.lock:
            messages, received_bytes = self.messages, self.bytes
        row = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "uptime_s": int(now - self.started),
            "messages_total": messages,
            "messages_per_s": round(
                (messages - previous["messages"]) / max(now - previous["time"], 1), 1
            ),
            "mb_total": round(received_bytes / 1e6, 1),
            "rss_mb": round(self.process.memory_info().rss / 1e6, 1),
            "cpu_pct": round(self.process.cpu_percent(interval=None), 1),
            "threads": self.process.num_threads(),
            "errors": len(self.ubwa.ringbuffer_error),
            "api_ok": self.api_ok,
            "api_failed": self.api_failed,
        }
        for name, stream_id in self.streams.items():
            manager = self.manager_of(name)
            info = manager.get_stream_info(stream_id) or {}
            row[f"{name}_status"] = str(info.get("status", "?"))[:12]
            row[f"{name}_reconnects"] = info.get("reconnects", "?")
            last = info.get("last_heartbeat") or 0
            row[f"{name}_last_data_s"] = int(now - last) if last else -1
            row[f"{name}_receives"] = info.get("processed_receives_total", "?")
        return row, {"messages": messages, "time": now}

    def run(self):
        self.started = time.time()
        end = self.started + self.args.hours * 3600
        previous = {"messages": 0, "time": self.started}
        write_header = not os.path.exists(self.csv_path)
        with open(self.csv_path, "a", newline="") as f:
            writer = None
            while not self.stop.is_set() and time.time() < end:
                self.stop.wait(self.args.interval)
                self.api_probe()
                row, previous = self.row(previous)
                if writer is None:
                    writer = csv.DictWriter(f, fieldnames=list(row))
                    if write_header:
                        writer.writeheader()
                writer.writerow(row)
                f.flush()
                print(
                    f"{row['timestamp']} msgs={row['messages_total']:,} ({row['messages_per_s']}/s) "
                    f"rss={row['rss_mb']}MB cpu={row['cpu_pct']}% "
                    + " ".join(
                        f"{n}={row[f'{n}_status']}/{row[f'{n}_reconnects']}"
                        for n in self.streams
                    ),
                    flush=True,
                )
        self.shutdown()

    def shutdown(self):
        print("stopping ...", flush=True)
        self.ubwa.stop_manager()
        if self.testnet is not None:
            self.testnet.stop_manager()
        time.sleep(3)  # let the DISCONNECT signals of the stopping streams land
        self.signals_file.close()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--library", default="picows", choices=["websockets", "picows"])
    parser.add_argument("--exchange", default="binance.com")
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--symbols", type=int, default=50)
    parser.add_argument(
        "--interval", type=int, default=60, help="seconds between metric rows"
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        filename=os.path.join(args.out, "ubwa.log"),
        format="{asctime} [{levelname:8}] {module}: {message}",
        style="{",
    )
    print(
        f"Python {platform.python_version()} {platform.system()} {platform.machine()}",
        flush=True,
    )
    soak = Soak(args)
    signal.signal(signal.SIGTERM, lambda *_: soak.stop.set())
    signal.signal(signal.SIGINT, lambda *_: soak.stop.set())
    soak.start()
    soak.run()


if __name__ == "__main__":
    main()
