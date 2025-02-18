from pydantic import BaseModel, Field


class VadeSecureConfiguration(BaseModel):
    client_id: str = Field(..., description="OAuth2 Client Identifier")
    client_secret: str = Field(secret=True, description="OAuth2 Client Secret")
    oauth2_authorization_url: str = Field(..., description="0Auth2 Authorization url")
    api_host: str = Field(..., description="API Url of the VadeSecure platform")


class VadeSecureTriggerConfiguration(BaseModel):
    tenant_id: str = Field(..., description="Identifier of your 365 Tenant")
    frequency: int = Field(..., description="Batch frequency in seconds")
    chunk_size: int = Field(10000, description="The max size of chunks for the batch processing")
