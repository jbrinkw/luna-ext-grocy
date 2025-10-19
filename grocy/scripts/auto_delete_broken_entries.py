#!/usr/bin/env python3
"""
AUTO-DELETE the OLD meal plan entries (with section_id = -1)
NO CONFIRMATION - runs automatically
"""
import json
import sys
from dotenv import load_dotenv

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import sys
from pathlib import Path
# Add lib directory to path
_lib_path = Path(__file__).parent.parent / "lib"
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

from core.client import GrocyClient


def main():
    load_dotenv()
    
    print("=" * 80)
    print("AUTO-DELETE OLD BROKEN MEAL PLAN ENTRIES")
    print("=" * 80)
    
    client = GrocyClient()
    
    try:
        # Get all meal plan entries
        all_entries = client.list_meal_plan()
        
        # Find broken entries (section_id = -1)
        broken_entries = [e for e in all_entries if e.get('section_id') == -1]
        good_entries = [e for e in all_entries if e.get('section_id') != -1]
        
        print(f"\nTotal entries: {len(all_entries)}")
        print(f"Broken (to delete): {len(broken_entries)}")
        print(f"Good (to keep): {len(good_entries)}")
        
        if len(broken_entries) == 0:
            print("\nNo broken entries found. Nothing to delete.")
            return 0
        
        print("\nDeleting broken entries:")
        print("-" * 80)
        
        deleted = 0
        failed = 0
        
        for entry in broken_entries:
            entry_id = entry.get('id')
            day = entry.get('day')
            
            try:
                client._delete(f"/objects/meal_plan/{entry_id}")
                print(f"  Deleted entry {entry_id} ({day})")
                deleted += 1
            except Exception as e:
                print(f"  FAILED entry {entry_id}: {e}")
                failed += 1
        
        print("\n" + "=" * 80)
        print("RESULT:")
        print("=" * 80)
        print(f"Deleted: {deleted}")
        print(f"Failed: {failed}")
        
        # Verify
        remaining = client.list_meal_plan()
        broken_remaining = [e for e in remaining if e.get('section_id') == -1]
        
        print(f"\nRemaining total entries: {len(remaining)}")
        print(f"Remaining broken entries: {len(broken_remaining)}")
        
        if len(broken_remaining) == 0:
            print("\nSUCCESS!")
            print("All broken entries deleted.")
            print("Your week cost should now update correctly when you refresh Grocy.")
        
        return 0
        
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

