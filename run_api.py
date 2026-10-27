"""
Entry point for the Formula Uno API.

Run with:   python run_api.py
Then open:  http://127.0.0.1:8000/docs   (interactive Swagger UI)
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.api.app:app", host="127.0.0.1", port=8000, reload=False)
