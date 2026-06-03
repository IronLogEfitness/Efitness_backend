"""Process entry point.

Run the API with:

    uvicorn main:app --reload
"""
from app import create_app

app = create_app()
