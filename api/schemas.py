from pydantic import BaseModel


class StationOut(BaseModel):
    code: str
    name: str
    city: str
