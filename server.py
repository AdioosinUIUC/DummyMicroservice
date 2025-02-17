from fastapi import FastAPI, HTTPException, Request
from utils.s3_logger import S3Logger, LogLevel
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional
import os
from contextvars import ContextVar
import uuid
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Load environment variables from .env file
load_dotenv()

trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)

# Initialize Logger
logger = S3Logger()

# FastAPI Microservice
# FastAPI application
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
logger = S3Logger()

@app.middleware("http")
async def log_exceptions_middleware(request: Request, call_next):
    with tracer.start_as_current_span("request") as span:
        trace_id = format(span.get_span_context().trace_id, "032x")
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            logger.log(f"Exception occurred: {str(e)}", LogLevel.ERROR)
            raise HTTPException(status_code=500, detail="Internal Server Error") from e

class LogRequest(BaseModel):
    message: str
    error: Optional[str] = ""

@app.post("/hello")
def log_message(request: LogRequest):
    logger.log(request.message, LogLevel.INFO)
    logger.log(request.error, LogLevel.ERROR)
    return {"status": "success", "message": "Hello world!!"}

@app.get("/")
def root():
    return {"message": "S3 Logger Microservice is running"}
