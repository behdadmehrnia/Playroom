from __future__ import annotations

from fastapi import FastAPI

from api.textbook.app.config import HOST, PORT
from api.textbook.app.routes import router

app = FastAPI(
    title="Yar Kids Textbook Service",
    description="Page-addressable retrieval for Iranian elementary textbooks (grades 3-6)",
    version="1.0.0",
)
app.include_router(router)


def main() -> None:
    import uvicorn

    uvicorn.run("api.textbook.app.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
