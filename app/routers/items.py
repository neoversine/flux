from fastapi import APIRouter, HTTPException
from typing import List
from app.models import Item, ItemCreate
from app.database import items_db, get_next_item_id

router = APIRouter()

@router.post("/items/", response_model=Item)
async def create_item(item: ItemCreate):
    item_id = get_next_item_id()
    db_item = {"id": item_id, **item.dict()}
    items_db[item_id] = db_item
    return Item(**db_item)

@router.get("/items/", response_model=List[Item])
async def read_items():
    return [Item(**item) for item in items_db.values()]

@router.get("/items/{item_id}", response_model=Item)
async def read_item(item_id: int):
    if item_id not in items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    return Item(**items_db[item_id])

@router.put("/items/{item_id}", response_model=Item)
async def update_item(item_id: int, item: ItemCreate):
    if item_id not in items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    db_item = {"id": item_id, **item.dict()}
    items_db[item_id] = db_item
    return Item(**db_item)

@router.delete("/items/{item_id}", response_model=Item)
async def delete_item(item_id: int):
    if item_id not in items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    deleted_item = items_db.pop(item_id)
    return Item(**deleted_item)
