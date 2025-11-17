#!/usr/bin/env python3
"""Start RQ worker for processing queued messages.

Usage:
    python scripts/start_worker.py [--queue default|high_priority|low_priority]

This script starts an RQ worker to process messages from the queue.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rq import Worker, Queue, Connection
from app.infra.queue import redis_conn, default_queue, high_priority_queue, low_priority_queue


def main():
    parser = argparse.ArgumentParser(description="Start RQ worker")
    parser.add_argument(
        "--queue",
        choices=["default", "high_priority", "low_priority"],
        default="default",
        help="Queue to process (default: default)",
    )
    parser.add_argument(
        "--burst",
        action="store_true",
        help="Run in burst mode (exit when queue is empty)",
    )
    
    args = parser.parse_args()
    
    # Select queue
    queue = {
        "default": default_queue,
        "high_priority": high_priority_queue,
        "low_priority": low_priority_queue,
    }[args.queue]
    
    print(f"Starting worker for queue: {args.queue}")
    if args.burst:
        print("Running in burst mode")
    
    # Start worker
    with Connection(redis_conn):
        worker = Worker([queue], connection=redis_conn)
        worker.work(burst=args.burst)


if __name__ == "__main__":
    main()

