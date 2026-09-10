"""
Meeting Provider Abstraction Layer for LMS Live Training Module.
Supports Zoom (Server-to-Server OAuth & REST APIs), Google Meet, and Custom/Manual links.
"""

import os
import json
import time
import hmac
import hashlib
import base64
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List


class BaseMeetingProvider:
    """Base interface for video conference providers."""

    def __init__(self, settings: Optional[Dict[str, str]] = None):
        self.settings = settings or {}

    def create_meeting(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a meeting on the provider platform.
        Returns dict with: meeting_id, meeting_uuid, join_url, host_url, passcode
        """
        raise NotImplementedError

    def get_meeting(self, meeting_id: str) -> Dict[str, Any]:
        """Retrieve meeting details."""
        raise NotImplementedError

    def cancel_meeting(self, meeting_id: str) -> bool:
        """Cancel or delete a meeting."""
        raise NotImplementedError

    def get_participants_report(self, meeting_id_or_uuid: str) -> List[Dict[str, Any]]:
        """
        Retrieve participant attendance report after the meeting has completed.
        Returns list of dicts: [
            {"user_name": str, "email": str, "join_time": str, "leave_time": str, "duration_seconds": int, "participant_id": str}
        ]
        """
        raise NotImplementedError


class CustomMeetingProvider(BaseMeetingProvider):
    """Fallback provider for manual or direct links."""

    def create_meeting(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        join_url = session_data.get("join_url", "").strip()
        host_url = session_data.get("host_url", "").strip() or join_url
        passcode = session_data.get("passcode", "").strip()
        meeting_id = session_data.get("meeting_id", "").strip() or f"CUSTOM-{int(time.time())}"
        return {
            "meeting_id": meeting_id,
            "meeting_uuid": meeting_id,
            "join_url": join_url,
            "host_url": host_url,
            "passcode": passcode,
            "provider": "custom"
        }

    def get_meeting(self, meeting_id: str) -> Dict[str, Any]:
        return {"meeting_id": meeting_id, "status": "active"}

    def cancel_meeting(self, meeting_id: str) -> bool:
        return True

    def get_participants_report(self, meeting_id_or_uuid: str) -> List[Dict[str, Any]]:
        return []


class GoogleMeetProvider(BaseMeetingProvider):
    """Google Meet conference provider."""

    def create_meeting(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        join_url = session_data.get("join_url", "").strip()
        passcode = session_data.get("passcode", "").strip()
        meeting_id = session_data.get("meeting_id", "").strip()

        if not join_url:
            # Generate clean Google Meet code format: abc-defg-hij
            import random
            import string
            p1 = ''.join(random.choices(string.ascii_lowercase, k=3))
            p2 = ''.join(random.choices(string.ascii_lowercase, k=4))
            p3 = ''.join(random.choices(string.ascii_lowercase, k=3))
            meeting_id = meeting_id or f"{p1}-{p2}-{p3}"
            join_url = f"https://meet.google.com/{meeting_id}"

        return {
            "meeting_id": meeting_id,
            "meeting_uuid": meeting_id,
            "join_url": join_url,
            "host_url": join_url,
            "passcode": passcode,
            "provider": "google_meet"
        }

    def get_meeting(self, meeting_id: str) -> Dict[str, Any]:
        return {"meeting_id": meeting_id, "status": "active"}

    def cancel_meeting(self, meeting_id: str) -> bool:
        return True

    def get_participants_report(self, meeting_id_or_uuid: str) -> List[Dict[str, Any]]:
        return []


class ZoomMeetingProvider(BaseMeetingProvider):
    """
    Zoom Meeting Provider supporting Server-to-Server OAuth 2.0 and fallback.
    """

    _token_cache: Dict[str, Any] = {}

    def _get_access_token(self) -> Optional[str]:
        account_id = self.settings.get("zoom_account_id") or os.environ.get("ZOOM_ACCOUNT_ID")
        client_id = self.settings.get("zoom_client_id") or os.environ.get("ZOOM_CLIENT_ID")
        client_secret = self.settings.get("zoom_client_secret") or os.environ.get("ZOOM_CLIENT_SECRET")

        if not (account_id and client_id and client_secret):
            return None

        # Check cache
        cached = self._token_cache.get(account_id)
        if cached and cached.get("expires_at", 0) > time.time() + 60:
            return cached.get("access_token")

        token_url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={account_id}"
        creds = f"{client_id}:{client_secret}".encode("utf-8")
        auth_header = f"Basic {base64.b64encode(creds).decode('utf-8')}"

        req = urllib.request.Request(
            token_url,
            method="POST",
            headers={"Authorization": auth_header, "Content-Type": "application/x-www-form-urlencoded"}
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    self._token_cache[account_id] = {
                        "access_token": access_token,
                        "expires_at": time.time() + expires_in
                    }
                    return access_token
        except Exception as e:
            print(f"[ZoomMeetingProvider] OAuth Token Error: {e}")
            return None
        return None

    def create_meeting(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        token = self._get_access_token()
        title = session_data.get("title", "Live Training Session")
        description = session_data.get("description", "")
        start_time_iso = session_data.get("scheduled_start")
        duration_minutes = session_data.get("duration_minutes", 60)
        timezone_str = session_data.get("timezone", "Asia/Kolkata")

        # Format ISO timestamp for Zoom API (e.g. 2026-09-10T10:00:00)
        formatted_start = start_time_iso.replace(" ", "T") if start_time_iso else ""

        if token:
            payload = {
                "topic": title,
                "type": 2,  # Scheduled meeting
                "start_time": formatted_start,
                "duration": duration_minutes,
                "timezone": timezone_str,
                "agenda": description[:2000] if description else "",
                "settings": {
                    "host_video": True,
                    "participant_video": True,
                    "join_before_host": False,
                    "mute_upon_entry": True,
                    "waiting_room": True,
                    "approval_type": 2,  # No registration required
                    "audio": "both",
                    "auto_recording": "none"
                }
            }

            req = urllib.request.Request(
                "https://api.zoom.us/v2/users/me/meetings",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            )

            try:
                with urllib.request.urlopen(req, timeout=12) as response:
                    if response.status in (200, 201):
                        res = json.loads(response.read().decode("utf-8"))
                        return {
                            "meeting_id": str(res.get("id")),
                            "meeting_uuid": str(res.get("uuid", res.get("id"))),
                            "join_url": res.get("join_url", ""),
                            "host_url": res.get("start_url", ""),
                            "passcode": str(res.get("password", "")),
                            "provider": "zoom"
                        }
            except Exception as e:
                print(f"[ZoomMeetingProvider] Create Meeting API Error: {e}")

        # Fallback if API not configured or offline:
        import random
        existing_url = session_data.get("join_url", "").strip()
        existing_host = session_data.get("host_url", "").strip()
        existing_id = session_data.get("meeting_id", "").strip()
        passcode = session_data.get("passcode", "").strip() or str(random.randint(100000, 999999))

        if not existing_id:
            existing_id = f"{int(time.time() * 1000) % 9000000000 + 1000000000}"

        if not existing_url:
            existing_url = f"https://zoom.us/j/{existing_id}?pwd={passcode}"
            existing_host = existing_host or f"https://zoom.us/s/{existing_id}?pwd={passcode}"

        return {
            "meeting_id": existing_id,
            "meeting_uuid": existing_id,
            "join_url": existing_url,
            "host_url": existing_host,
            "passcode": passcode,
            "provider": "zoom"
        }

    def cancel_meeting(self, meeting_id: str) -> bool:
        token = self._get_access_token()
        if not token or not meeting_id:
            return True
        try:
            req = urllib.request.Request(
                f"https://api.zoom.us/v2/meetings/{meeting_id}",
                method="DELETE",
                headers={"Authorization": f"Bearer {token}"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status in (200, 204)
        except Exception:
            return False

    def get_participants_report(self, meeting_id_or_uuid: str) -> List[Dict[str, Any]]:
        token = self._get_access_token()
        if not token or not meeting_id_or_uuid:
            return []

        # Zoom expects double-encoding if meeting UUID contains / or starts with /
        encoded_id = urllib.parse.quote(urllib.parse.quote(meeting_id_or_uuid, safe=''), safe='')
        url = f"https://api.zoom.us/v2/report/meetings/{encoded_id}/participants?page_size=300"

        req = urllib.request.Request(
            url,
            method="GET",
            headers={"Authorization": f"Bearer {token}"}
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    participants = []
                    for p in data.get("participants", []):
                        participants.append({
                            "user_name": p.get("name", ""),
                            "email": p.get("user_email", "").strip().lower(),
                            "join_time": p.get("join_time", ""),
                            "leave_time": p.get("leave_time", ""),
                            "duration_seconds": p.get("duration", 0),
                            "participant_id": p.get("id", "") or p.get("user_id", "")
                        })
                    return participants
        except Exception as e:
            print(f"[ZoomMeetingProvider] Participant Report Error: {e}")
            return []
        return []

    @staticmethod
    def verify_webhook_signature(secret_token: str, request_headers: Dict[str, str], request_body: bytes) -> bool:
        """Verify Zoom webhook CRC and HMAC-SHA256 signature."""
        if not secret_token:
            return True
        timestamp = request_headers.get("x-zm-request-timestamp", "")
        signature = request_headers.get("x-zm-signature", "")
        if not (timestamp and signature):
            return False
        message = f"v0:{timestamp}:{request_body.decode('utf-8', errors='ignore')}".encode("utf-8")
        expected_sig = "v0=" + hmac.new(secret_token.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_sig, signature)

    @staticmethod
    def generate_crc_response(secret_token: str, plain_token: str) -> Dict[str, str]:
        """Generate response for Zoom Webhook URL Validation Challenge."""
        hash_bytes = hmac.new(secret_token.encode("utf-8"), plain_token.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "plainToken": plain_token,
            "encryptedToken": hash_bytes
        }


def get_meeting_provider(provider_type: str, settings: Optional[Dict[str, str]] = None) -> BaseMeetingProvider:
    """Factory function for meeting providers."""
    ptype = (provider_type or "zoom").lower().strip()
    if ptype == "zoom":
        return ZoomMeetingProvider(settings)
    elif ptype in ("google_meet", "meet"):
        return GoogleMeetProvider(settings)
    else:
        return CustomMeetingProvider(settings)

