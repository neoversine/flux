from typing import Dict, List

# In-memory database for demonstration purposes
items_db: Dict[int, Dict] = {}
next_item_id: int = 1

def get_next_item_id() -> int:
    global next_item_id
    _id = next_item_id
    next_item_id += 1
    return _id
