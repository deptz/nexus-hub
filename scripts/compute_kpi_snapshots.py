#!/usr/bin/env python3
"""Periodic job script to compute tenant KPI snapshots.

Usage:
    python scripts/compute_kpi_snapshots.py [--period daily|weekly|monthly] [--tenant-id UUID]

This script can be run as a cron job:
    # Daily at 2 AM
    0 2 * * * cd /path/to/nexus-hub && /path/to/venv/bin/python scripts/compute_kpi_snapshots.py --period daily
    
    # Weekly on Monday at 3 AM
    0 3 * * 1 cd /path/to/nexus-hub && /path/to/venv/bin/python scripts/compute_kpi_snapshots.py --period weekly
    
    # Monthly on 1st at 4 AM
    0 4 1 * * cd /path/to/nexus-hub && /path/to/venv/bin/python scripts/compute_kpi_snapshots.py --period monthly
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.services.kpi_computation import compute_tenant_kpi_snapshots


async def main():
    parser = argparse.ArgumentParser(description="Compute tenant KPI snapshots")
    parser.add_argument(
        "--period",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="Period type to compute (default: daily)",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default=None,
        help="Optional tenant ID to compute for specific tenant (default: all tenants)",
    )
    
    args = parser.parse_args()
    
    print(f"Computing {args.period} KPI snapshots...")
    if args.tenant_id:
        print(f"  Tenant: {args.tenant_id}")
    else:
        print("  All tenants")
    
    try:
        await compute_tenant_kpi_snapshots(
            tenant_id=args.tenant_id,
            period_type=args.period,
        )
        print("✓ KPI snapshots computed successfully")
    except Exception as e:
        print(f"✗ Error computing KPI snapshots: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

