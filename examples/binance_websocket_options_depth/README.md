# Binance WebSocket Options Depth
## Overview
Stream European Options (Vanilla Options) order book depth data via WebSocket.

Options symbols use the format `UNDERLYING-YYMMDD-STRIKE-C/P`, e.g. `btc-260626-120000-c`.

## Prerequisites
Ensure you have Python 3.9+ installed on your system.

Before running the provided script, install the required Python packages:
```bash
pip install -r requirements.txt
```

No API key is needed for public market data streams.

## Available Depth Channels
| Channel | Description |
|---------|-------------|
| `depth@500ms` | Diff depth stream, 500ms updates |
| `depth@100ms` | Diff depth stream, 100ms updates |
| `depth5@500ms` | Partial book depth, top 5 levels |
| `depth10@500ms` | Partial book depth, top 10 levels |
| `depth20@500ms` | Partial book depth, top 20 levels |

## Usage
### Running the Script:
```bash
python binance_websocket_options_depth.py
```

### Graceful Shutdown:
The script handles a graceful shutdown upon receiving a KeyboardInterrupt (Ctrl+C).

## Logging
Logs are saved to a file named after the script with a `.log` extension.

For further assistance or to report issues, please
[visit the GitHub repository](https://github.com/oliver-zehentleitner/unicorn-binance-websocket-api).
