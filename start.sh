#!/bin/sh
# Start the Sticklink window (Start/Stop, status, page links).
cd "$(dirname "$0")" && exec uv run sticklink gui "$@"
