import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.models.recipe import RecipeVersionSnapshot
from app.core.config import get_settings

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Check an explicit version ID from previous run: 6a99be92-9756-4210-b9bc-5f936233601c
        result = await session.execute(
            select(RecipeVersionSnapshot)
            .where(RecipeVersionSnapshot.version_id == "6a99be92-9756-4210-b9bc-5f936233601c")
        )
        snap = result.scalar_one_or_none()
        if snap:
            print(f"DEBUG: {snap.snapshot_json.get('metadata')}")
        else:
            print("NOT FOUND")

if __name__ == "__main__":
    asyncio.run(main())
