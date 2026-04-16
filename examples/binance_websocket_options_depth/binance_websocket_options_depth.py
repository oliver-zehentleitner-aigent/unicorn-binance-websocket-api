#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ¯\_(ツ)_/¯

from unicorn_binance_websocket_api import BinanceWebSocketApiManager
import asyncio
import logging
import os


async def options_depth_stream(ubwa):
    """Stream European Options depth data for multiple symbols."""

    async def handle_socket_message(stream_id=None):
        while ubwa.is_stop_request(stream_id=stream_id) is False:
            data = await ubwa.get_stream_data_from_asyncio_queue(stream_id=stream_id)
            if data and isinstance(data, dict):
                event = data.get("data", data)
                if event.get("e") == "depthUpdate":
                    symbol = event.get("s", "?")
                    bids = len(event.get("b", []))
                    asks = len(event.get("a", []))
                    u = event.get("u")
                    pu = event.get("pu")
                    print(f"[{symbol}] depthUpdate u={u} pu={pu} bids={bids} asks={asks}")
                else:
                    print(f"Received: {data}")

    # Options symbols use the format: UNDERLYING-YYMMDD-STRIKE-C/P (lowercase for stream names)
    # Adjust these to currently listed options on Binance
    markets = [
        "btc-260626-120000-c",
        "btc-260626-120000-p",
    ]

    # depth@500ms = diff depth stream (500ms update interval)
    # depth@100ms = diff depth stream (100ms update interval)
    # depth5@500ms = partial book depth, top 5 levels
    # depth10@500ms = partial book depth, top 10 levels
    # depth20@500ms = partial book depth, top 20 levels
    stream_id = ubwa.create_stream(
        channels=["depth@500ms"],
        markets=markets,
        stream_label="options_depth",
        process_asyncio_queue=handle_socket_message,
    )

    print(f"Streaming Options depth for {len(markets)} symbols ...")
    print(f"Stream ID: {stream_id}")
    print(f"Press Ctrl+C to stop.\n")

    while ubwa.is_manager_stopping() is False:
        await asyncio.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        filename=os.path.basename(__file__) + ".log",
        format="{asctime} [{levelname:8}] {process} {thread} {module}: {message}",
        style="{",
    )

    with BinanceWebSocketApiManager(
        exchange="binance.com-vanilla-options",
        output_default="dict",
    ) as ubwa_manager:
        try:
            asyncio.run(options_depth_stream(ubwa_manager))
        except KeyboardInterrupt:
            print("\r\nGracefully stopping the websocket manager...")
