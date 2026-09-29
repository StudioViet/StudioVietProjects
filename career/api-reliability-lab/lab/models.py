from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    external_reference: str = Field(min_length=1, max_length=60, examples=["DEMO-1042"])
    asset_id: str = Field(pattern=r"^ASSET-\d{4}$", examples=["ASSET-0042"])
    action: Literal["inspect", "restore"] = "inspect"
    priority: Literal["normal", "urgent"] = "normal"


class CompletionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^evt_[a-zA-Z0-9_-]{1,80}$")
    type: Literal["work_order.completed"]
    work_order_id: str = Field(pattern=r"^wo_[a-f0-9]{12}$")


class WebhookDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_order_id: str = Field(pattern=r"^wo_[a-f0-9]{12}$")
    event_id: str = Field(default="evt_demo", pattern=r"^evt_[a-zA-Z0-9_-]{1,80}$")
    mode: Literal["valid", "tampered", "expired"] = "valid"


Scenario = Literal[
    "healthy", "rate_limit", "unavailable", "lost_response",
    "permanent_failure", "provider_auth", "long_rate_limit",
]
