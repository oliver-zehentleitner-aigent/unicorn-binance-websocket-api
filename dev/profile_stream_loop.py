#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# File: dev/profile_stream_loop.py
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
cProfile the UBWA stream thread while it receives one benchmark scenario from
the local replay server of `dev/test_websocket_library_benchmark.py`.

Shows where UBWA's own per-message time goes (on top of the WebSocket
library). Not part of CI. Numbers under cProfile are inflated (~3x), the
call counts and the relative distribution are what matters; use the
benchmark script for absolute numbers.

Usage:
    python3 dev/profile_stream_loop.py [websockets|picows] [scenario] [raw_data|dict]
    python3 dev/profile_stream_loop.py picows small_aggtrade raw_data
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_websocket_library_benchmark as bench  # noqa: E402
from unicorn_binance_websocket_api.manager import (  # noqa: E402
    BinanceWebSocketApiManager,
)
import cProfile  # noqa: E402
import io  # noqa: E402
import multiprocessing  # noqa: E402
import pstats  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

PORT = 18773


def main():
    library = sys.argv[1] if len(sys.argv) > 1 else "picows"
    scenario = sys.argv[2] if len(sys.argv) > 2 else "small_aggtrade"
    output = sys.argv[3] if len(sys.argv) > 3 else "raw_data"

    ready = multiprocessing.Event()
    server = multiprocessing.Process(
        target=bench.server_process, args=(PORT, ready), daemon=True
    )
    server.start()
    ready.wait(10)

    profiles = {}
    original = BinanceWebSocketApiManager._create_stream_thread

    def profiled(self, *args, **kwargs):
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            return original(self, *args, **kwargs)
        finally:
            profiler.disable()
            profiles[threading.current_thread().name] = profiler

    BinanceWebSocketApiManager._create_stream_thread = profiled

    _, count = bench.SCENARIOS[scenario]
    counter = bench.Counter(count)
    ubwa = BinanceWebSocketApiManager(
        exchange="binance.com",
        websocket_library=library,
        websocket_base_uri=f"ws://127.0.0.1:{PORT}/",
        output_default=output,
        process_stream_data=counter,
        warn_on_update=False,
        disable_colorama=True,
        ping_interval_default=None,
        ping_timeout_default=None,
    )
    ubwa.create_stream(["bench"], [scenario])
    counter.done.wait(120)
    wall = counter.last - counter.first
    ubwa.stop_manager()
    # The server close ends the untimed recv() of the stream thread, see
    # context/stream-loop.md
    server.terminate()
    for _ in range(100):
        if profiles:
            break
        time.sleep(0.1)

    out = io.StringIO()
    stats = pstats.Stats(list(profiles.values())[0], stream=out)
    stats.sort_stats("tottime").print_stats(30)
    print(f"{library} {scenario} {output}: {count / wall:,.0f} msgs/s under cProfile")
    print(out.getvalue())


if __name__ == "__main__":
    main()
