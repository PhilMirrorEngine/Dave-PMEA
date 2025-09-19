# --- OpenAPI "servers" fix so GPT Builder can import cleanly -------------
from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="Dave-PMEA",
        version="0.1.0",
        routes=app.routes,
        description="OpenAPI for Dave-PMEA"
    )
    schema["servers"] = [{"url": "https://dave-pmea.onrender.com"}]
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
app.openapi = custom_openapi
# --- OpenAPI "servers" fix so GPT Builder can import cleanly -------------
from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="Dave-PMEA",
        version="0.1.0",
        routes=app.routes,
        description="OpenAPI for Dave-PMEA"
    )
    schema["servers"] = [{"url": "https://dave-pmea.onrender.com"}]
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
