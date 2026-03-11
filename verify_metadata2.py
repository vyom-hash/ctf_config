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
        # Check all snapshots
        result = await session.execute(select(RecipeVersionSnapshot))
        for snap in result.scalars().all():
            meta = snap.snapshot_json.get('metadata')
            if meta and meta.get('sub_category'):
                print(f"FOUND LATEST SNAPSHOT WITH SUBCAT: {meta}")
        
        # Check deployments
        result = await session.execute(select(Deployment))
        for dep in result.scalars().all():
            if dep.recipe_spec:
                meta = dep.recipe_spec.get('metadata')
                if meta and meta.get('sub_category'):
                    print(f"FOUND DEPLOYMENT WITH SUBCAT: {meta}")

if __name__ == "__main__":
    asyncio.run(main())
