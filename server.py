from fastapi import FastAPI, HTTPException, Request
from utils.s3_logger import S3Logger, LogLevel
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional
import os
# from opentelemetry import trace
# from opentelemetry.sdk.trace import TracerProvider
# from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from elasticapm.contrib.starlette import ElasticAPM, make_apm_client
import logging
import elasticapm
from elasticapm.handlers.logging import LoggingHandler
import json


# Load environment variables from .env file
load_dotenv()

# Initialize FastAPI
app = FastAPI()

# Elastic APM
apm_client = elasticapm.Client({
    "SERVICE_NAME": "fastapi-service",
    "SERVER_URL": "http://localhost:8200",  # Connects to APM running in Docker
    "CAPTURE_HEADERS": True,
    "TRANSACTIONS_IGNORE_PATTERNS": ["OPTIONS"],
    "VERIFY_SERVER_CERT": False,
    "SERVER_TIMEOUT": 20,
})


class CustomJSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "service": "fastapi-service",
            "trace_id": elasticapm.get_trace_id(),  # Link logs to APM traces
            "transaction_id": elasticapm.get_transaction_id(),
            "span_id": elasticapm.get_span_id(),
        }

        # Include exception details if an error occurred
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Include extra fields if present
        if record.args:
            log_data["extra"] = record.args

        return json.dumps(log_data)


app.add_middleware(ElasticAPM, client=apm_client)
logger = logging.getLogger("fastapi_logger")
logger.setLevel(logging.INFO)

apm_handler = LoggingHandler(client=apm_client)
apm_handler.setFormatter(CustomJSONFormatter())
logger.addHandler(apm_handler)

# S3 logging traceId generation
# trace.set_tracer_provider(TracerProvider())
# tracer = trace.get_tracer(__name__)
# FastAPIInstrumentor.instrument_app(app)
# logger = S3Logger()

@app.middleware("http")
async def log_exceptions_middleware(request: Request, call_next):
    # with tracer.start_as_current_span("request") as span:
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        # logger.log(f"Exception occurred: {str(e)}", LogLevel.ERROR)
        logger.error(f"Exception occurred: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error") from e

class LogRequest(BaseModel):
    message: str
    error: Optional[str] = ""

@app.post("/hello")
def log_message(request: LogRequest):
    logger.info(request.message)
    logger.error(request.error)
    return {"status": "success", "message": "Hello world!!"}

@app.get("/")
def root():
    return {"message": "S3 Logger Microservice is running"}
