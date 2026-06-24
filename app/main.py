import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db import init_db
from app.scheduler import start_scheduler, shutdown_scheduler
from app.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="Job Radar", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run")
async def run_now():
    await run_pipeline()
    return {"status": "triggered"}
