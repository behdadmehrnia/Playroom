from __future__ import annotations

from fastapi import FastAPI

from textbook_service.app.config import HOST, PORT
from textbook_service.app.routes import router

app = FastAPI(
    title="Yar Kids Textbook Service",
    description="Page-addressable retrieval for Iranian elementary textbooks (grades 3-6)",
    version="1.0.0",
)
app.include_router(router)


def main() -> None:
    import uvicorn

    uvicorn.run("textbook_service.app.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
