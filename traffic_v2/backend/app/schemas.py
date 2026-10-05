from typing import Literal, Optional

from pydantic import BaseModel, Field


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, description="video file path, rtsp:// URL, or webcam index like 0")
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    road_type: str = "highway"
    enabled: bool = True
    loop: bool = False
    realtime: bool = True


class CameraPatch(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    road_type: Optional[str] = None
    enabled: Optional[bool] = None
    loop: Optional[bool] = None
    realtime: Optional[bool] = None


class AuthorityIn(BaseModel):
    name: str = Field(min_length=1)
    type: Literal["police", "hospital", "traffic_control", "fire"]
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: Optional[str] = None
    active: bool = True


class AuthorityPatch(BaseModel):
    name: Optional[str] = None
    type: Optional[Literal["police", "hospital", "traffic_control", "fire"]] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    email: Optional[str] = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: Optional[str] = None
    active: Optional[bool] = None


class ConfirmIn(BaseModel):
    note: Optional[str] = None


class DismissIn(BaseModel):
    reason: Literal["false_alarm", "duplicate", "other"] = "false_alarm"
    note: Optional[str] = None


class AlertPatch(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
