from pydantic import BaseModel

class AuthMeResponse(BaseModel):
    authenticated: bool
    user_id: str | None = None
    email: str | None = None
    name: str | None = None


class IntegrationStatusResponse(BaseModel):
    provider: str
    connected: bool
