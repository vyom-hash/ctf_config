import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.models.recipe import RecipeVersionSnapshot
from app.models.deployment import Deployment
from app.core.config import get_settings

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Check all snapshots with subcat
        result = await session.execute(select(RecipeVersionSnapshot))
        count = 0
        for snap in result.scalars().all():
            m = snap.snapshot_json.get('metadata', {})
            if m.get('sub_category') == 'selfpaced':
                print(f"SUCCESS - Found snapshot {snap.version_id} with sub_category: {m.get('sub_category')}")
                count += 1
        
        if count == 0:
            print("FAILURE - Could not find any snapshots with sub_category='selfpaced'")

if __name__ == "__main__":
    asyncio.run(main())
