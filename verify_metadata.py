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
        result = await session.execute(
            select(RecipeVersionSnapshot)
            .order_by(RecipeVersionSnapshot.version_id.desc())
            .limit(1)
        )
        snap = result.scalar_one_or_none()
        if snap:
            print(f"LATEST SNAPSHOT: {snap.snapshot_json.get('metadata')}")
            
        result = await session.execute(
            select(Deployment)
            .order_by(Deployment.created_at.desc())
            .limit(1)
        )
        dep = result.scalar_one_or_none()
        if dep:
            print(f"LATEST DEPLOYMENT RECIPE SPEC: {dep.recipe_spec.get('metadata')}")

if __name__ == "__main__":
    asyncio.run(main())
