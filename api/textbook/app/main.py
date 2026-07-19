from __future__ import annotations

from fastapi import FastAPI

from api.textbook.app.config import HOST, PORT
from api.textbook.app.models import HealthResponse
from api.textbook.app.routes import router
from api.textbook.app.store import index_exists, load_catalog, page_count

app = FastAPI(
    title="Yar Kids Textbook Service",
    description="Page-addressable retrieval for Iranian elementary textbooks (grades 3-6)",
    version="1.0.0",
    openapi_tags=[
        {
            "name": "Health",
            "description": "Index and catalog status",
        },
        {
            "name": "Textbook",
            "description": "Retrieve pages, images, and manage the textbook index",
        },
    ],
)
app.include_router(router, tags=["Textbook"])


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        index_exists=index_exists(),
        page_count=page_count(),
        catalog_books=len(load_catalog()),
    )


def main() -> None:
    import uvicorn

    uvicorn.run("api.textbook.app.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
