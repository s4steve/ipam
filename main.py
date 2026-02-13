from fastapi import FastAPI
from health import router as health_router
from subnets import router as subnets_router
from database import Base, engine
import models  # noqa: F401 - ensures tables are registered

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.include_router(health_router)
app.include_router(subnets_router)


@app.get("/")
async def root():
    return {"message": "Hello, World!"}
